from dataclasses import dataclass, field
from Packet import Packet
from Channel import Channel
from collections import deque
from dbg_print import dbg_print


@dataclass
class sender_info:
    id: str
    last_sent_timestep: int
    send_times: int
    next_send_timestep: int
    interval_history: deque[int]
    min_interval: int = 3600000  # 初始设为1小时
    channel_index: int = -1
    interval_frequency: dict = field(default_factory=dict)

    def append_interval(self, interval: int):
        # 维护间隔历史、最小间隔和各间隔频率字典
        if interval < self.min_interval:
            self.min_interval = interval
        if len(self.interval_history) == self.interval_history.maxlen:
            # 最小间隔要保留，其余都可以删除
            if self.interval_history[0] == self.min_interval:
                self.interval_frequency[self.interval_history[1]] -= 1
                del self.interval_history[1]
            else:
                self.interval_frequency[self.interval_history.popleft()] -= 1
        self.interval_history.append(interval)
        self.interval_frequency[interval] = self.interval_frequency.get(interval, 0) + 1

    @property
    def last_interval(self) -> int:
        return self.interval_history[-1] if self.interval_history else -1

    @property
    def average_interval(self) -> float:
        if not self.interval_history:
            return -1.0
        return sum(self.interval_history) / len(self.interval_history)

    @property
    def mode_interval(self) -> int:
        if not self.interval_frequency:
            return -1
        mode = max(self.interval_frequency, key=self.interval_frequency.get)
        return mode

    @property
    def content_interval(self) -> list:
        return list(self.interval_history)


class Receiver:
    """
    packet receiver
    """

    def __init__(
        self,
        channels: list,
        index: int,
        channel_switch_time,
        channel_dwell_time,
        uni_sender_info: dict = None,
        uni_senders_channel_index: list = None,
    ):
        self.recver_index = index
        self.managed_channels: list[Channel] = channels
        self.poll_channel_idx = 0
        self.active_channel_idx = 0

        self.state = "DWELL"  # or "SWITCH" or "SCHEDULE" or "SWITCH_TO_SCHEDULE" ("DWELL" used as "IDLE" in only scheduling mode)

        self.switch_time = channel_switch_time
        self.switch_timer = 0
        self.expected_dwell_time = channel_dwell_time
        self.dwell_timer = 0
        self.max_schedule_timeout = channel_dwell_time
        self.schedule_timeout_timer = 0
        self.schedule_timeout_counter = 0

        self.senders_info = {} if uni_sender_info is None else uni_sender_info
        self.senders_channel_index = [] if uni_senders_channel_index is None else uni_senders_channel_index
        self.first_switch_loop = False

    @property
    def current_channel(self):
        return self.managed_channels[self.active_channel_idx]

    def poll_to_next_channel(self, channel_limited=False):
        if channel_limited:
            if self.poll_channel_idx in self.senders_channel_index:
                next_poll_idx = self.senders_channel_index[
                    (self.senders_channel_index.index(self.poll_channel_idx) - 1)
                    % len(self.senders_channel_index)
                ]
            else:
                next_poll_idx = self.senders_channel_index[0] if self.senders_channel_index else self.poll_channel_idx
        else:
            next_poll_idx = (self.poll_channel_idx + 1) % len(self.managed_channels)
        if next_poll_idx != self.active_channel_idx:
            self.state = "SWITCH"
        self.poll_channel_idx = next_poll_idx

    def switch_to_channel(self, idx: int):
        if 0 <= idx < len(self.managed_channels):
            self.active_channel_idx = idx
        else:
            raise IndexError("Channel index out of range.")

    def record_sender_info(self, packet: Packet, cur_timestep) -> int:
        # 记录发送者信道
        if self.poll_channel_idx not in self.senders_channel_index:
            self.senders_channel_index.append(self.poll_channel_idx)
        # 首次收到包，初始化发送者信息
        if packet.packet_id not in self.senders_info:
            self.senders_info[packet.packet_id] = sender_info(
                id=packet.packet_id,
                channel_index=self.poll_channel_idx,
                last_sent_timestep=cur_timestep,
                interval_history=deque(maxlen=100),
                send_times=1,
                next_send_timestep=-1,
            )
            return 0
        else:  # 已有发送者记录，更新信息并预计发送时间
            info: sender_info = self.senders_info[packet.packet_id]
            info.append_interval(cur_timestep - info.last_sent_timestep)
            info.last_sent_timestep = cur_timestep
            info.send_times += 1

            # 规划下次接收包的时间，如果太短不足1s要延展到1s以上，以免频繁切换信道
            next_send_timestep = cur_timestep + info.min_interval
            while next_send_timestep - cur_timestep < 1000:
                next_send_timestep += info.min_interval
            info.next_send_timestep = next_send_timestep

            return info.send_times

    def next_schedule_recv_time(self, cur_timestep, info: sender_info) -> int:
        if info.next_send_timestep > 0:  # 有计划时间
            while info.next_send_timestep < cur_timestep:
                # 错过接收时间，说明计划失败，重新规划下次接收时间
                info.next_send_timestep = cur_timestep + info.min_interval
        return info.next_send_timestep - cur_timestep

    def packet_recv(self, cur_timestep=0, just_polling=False, limited_polling=False) -> tuple[str, bool]:
        if not just_polling:
            # 不在切换状态时，先判断是否有计划数据包，如果有则优先接收，否则再进入轮询驻留模式
            if self.state == "DWELL":
                sender_schedule_time_min = 100000  # 一个很大的数
                active_channel_index = -1
                delete_ids = []
                for sender_id, info in self.senders_info.items():
                    # 计算下次计划接收时间
                    sender_schedule_time = self.next_schedule_recv_time(
                        cur_timestep, info
                    )
                    # 一小时没包，记录ID准备删除
                    if sender_schedule_time > 3600 * 1000:
                        delete_ids.append(sender_id)
                        continue
                    if (
                        0 < sender_schedule_time < 20
                        and sender_schedule_time < sender_schedule_time_min
                    ):
                        sender_schedule_time_min = sender_schedule_time
                        active_channel_index = info.channel_index
                # 开删！
                for did in delete_ids:
                    del self.senders_info[did]

                if active_channel_index != -1:
                    if active_channel_index != self.poll_channel_idx:
                        # 切换到该发送者所在频道接收数据包
                        self.current_channel.quit_listen()
                        self.state = "SWITCH_TO_SCHEDULE"
                        self.switch_to_channel(active_channel_index)
                        self.active_channel_idx = active_channel_index
                    else:
                        # 已经在该频道，直接进入计划状态接收数据包
                        self.state = "SCHEDULE"

        if self.state == "SWITCH":
            # 在切换时间内，不接收数据包
            if self.switch_timer < self.switch_time:
                self.switch_timer += 1
                if self.first_switch_loop:
                    dbg_print(
                        f"Receiver {self.recver_index}: Switching to polling channel"
                    )
                    self.first_switch_loop = False

            else:
                # 切换完成，进入停留状态
                self.first_switch_loop = True
                self.switch_timer = 0
                self.state = "DWELL"
                dbg_print(
                    f"Receiver {self.recver_index}: Switched to channel {self.poll_channel_idx }"
                )

        elif self.state == "SWITCH_TO_SCHEDULE":
            # 在切换到计划包信道的时间内，不接收数据包
            if self.switch_timer < self.switch_time:
                self.switch_timer += 1
                if self.first_switch_loop:
                    dbg_print(
                        f"Receiver {self.recver_index}: Switching to scheduled channel..."
                    )
                    self.first_switch_loop = False

            else:
                # 切换完成，进入计划状态
                self.first_switch_loop = True
                self.switch_timer = 0
                self.state = "SCHEDULE"
                dbg_print(
                    f"Receiver {self.recver_index}: Switched to scheduled channel {self.active_channel_idx }"
                )
        elif self.state == "SCHEDULE":
            self.current_channel.listen()
            # 在计划时间内，接收数据包
            if self.schedule_timeout_timer < self.max_schedule_timeout:
                self.schedule_timeout_timer += 1
                for _ in self.current_channel.packets:
                    p = self.current_channel.packet_pop()
                    dbg_print(
                        f"Receiver {self.recver_index}: (Scheduled) Received Packet {p.packet_id} from channel {self.active_channel_idx }"
                    )
                    # 记录发送者信息
                    self.record_sender_info(p, cur_timestep)

                    # 接收到计划包，恢复轮询状态
                    self.current_channel.quit_listen()
                    self.schedule_timeout_timer = 0
                    temp_state = self.state
                    if self.poll_channel_idx != self.active_channel_idx:
                        self.state = "SWITCH"
                    else:
                        self.state = "DWELL"
                    dbg_print(
                        f"Receiver {self.recver_index}: Schedule Received, switching to dwell state"
                    )
                    return (temp_state, True)
            else:
                # 计划时间结束，恢复轮询状态
                self.current_channel.quit_listen()
                self.schedule_timeout_timer = 0
                self.schedule_timeout_counter += 1
                if self.poll_channel_idx != self.active_channel_idx:
                    self.state = "SWITCH"
                else:
                    self.state = "DWELL"
                dbg_print(
                    f"Receiver {self.recver_index}: Schedule timeout, switching to dwell state"
                )
        elif self.state == "DWELL":
            # 同步活动频道索引
            self.active_channel_idx = self.poll_channel_idx
            self.current_channel.listen()
            # 在停留时间内，接收数据包
            if self.dwell_timer < self.expected_dwell_time:
                self.dwell_timer += 1
                p = self.current_channel.packet_pop()
                if p:
                    dbg_print(
                        f"Receiver {self.recver_index}: Received Packet {p.packet_id} from channel {self.poll_channel_idx }"
                    )
                    # 记录发送者信息，如果是第一次发包，等待下一次发包以便计算间隔
                    if not self.record_sender_info(p, cur_timestep):
                        self.dwell_timer = 0  # 重置停留时间，等待下一次发包
                    return (self.state, True)
                else:
                    # dbg_print(f"Receiver {self.sender_index}: No Packet in channel {self.poll_channel_idx }")
                    pass
            else:
                # 停留时间结束，进入切换状态
                self.current_channel.quit_listen()
                self.dwell_timer = 0
                self.poll_to_next_channel(limited_polling)  # 切换状态，切换频道
                dbg_print(
                    f"Receiver {self.recver_index}: Dwell time ended, switching to next channel {self.poll_channel_idx }"
                )
        return (self.state, False)

    def packet_schedule_recv(self, cur_timestep=0) -> tuple[str, bool]:
        if self.state == "DWELL":
            sender_schedule_time_min = 100000  # 一个很大的数
            active_channel_index = -1
            delete_ids = []
            for sender_id, info in self.senders_info.items():
                # 计算下次计划接收时间
                sender_schedule_time = self.next_schedule_recv_time(cur_timestep, info)
                # 一小时没包，记录ID准备删除
                if sender_schedule_time > 3600 * 1000:
                    delete_ids.append(sender_id)
                    continue
                if (
                    0 < sender_schedule_time < 20
                    and sender_schedule_time < sender_schedule_time_min
                ):
                    sender_schedule_time_min = sender_schedule_time
                    active_channel_index = info.channel_index
            # 开删！
            for did in delete_ids:
                del self.senders_info[did]

            if active_channel_index != -1:
                if active_channel_index != self.poll_channel_idx:
                    # 切换到该发送者所在频道接收数据包
                    self.current_channel.quit_listen()
                    self.state = "SWITCH_TO_SCHEDULE"
                    self.switch_to_channel(active_channel_index)
                    self.active_channel_idx = active_channel_index
                else:
                    # 已经在该频道，直接进入计划状态接收数据包
                    self.state = "SCHEDULE"

        elif self.state == "SWITCH_TO_SCHEDULE":
            # 在切换到计划包信道的时间内，不接收数据包
            if self.switch_timer < self.switch_time:
                self.switch_timer += 1
                if self.first_switch_loop:
                    dbg_print(
                        f"Receiver {self.recver_index}: Switching to scheduled channel..."
                    )
                    self.first_switch_loop = False

            else:
                # 切换完成，进入计划状态
                self.first_switch_loop = True
                self.switch_timer = 0
                self.state = "SCHEDULE"
                dbg_print(
                    f"Receiver {self.recver_index}: Switched to scheduled channel {self.active_channel_idx }"
                )
        elif self.state == "SCHEDULE":
            self.current_channel.listen()
            # 在计划时间内，接收数据包
            if self.schedule_timeout_timer < self.max_schedule_timeout:
                self.schedule_timeout_timer += 1
                for _ in self.current_channel.packets:
                    p = self.current_channel.packet_pop()
                    dbg_print(
                        f"Receiver {self.recver_index}: (Scheduled) Received Packet {p.packet_id} from channel {self.active_channel_idx }"
                    )
                    # 记录发送者信息
                    self.record_sender_info(p, cur_timestep)

                    # 接收到计划包，恢复轮询状态
                    self.current_channel.quit_listen()
                    self.schedule_timeout_timer = 0
                    self.schedule_timeout_counter += 1
                    temp_state = "SCHEDULE"
                    self.state = "DWELL"
                    dbg_print(
                        f"Receiver {self.recver_index}: Schedule Received, switching to dwell state"
                    )
                    return (temp_state, True)
            else:
                # 计划时间结束，恢复轮询状态
                self.current_channel.quit_listen()
                self.schedule_timeout_timer = 0
                self.schedule_timeout_counter += 1
                self.state = "DWELL"
                dbg_print(
                    f"Receiver {self.recver_index}: Schedule timeout, switching to dwell state"
                )
        return (self.state, False)
