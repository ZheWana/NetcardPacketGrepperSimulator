from datetime import datetime
import os
import csv
import random
from tqdm import tqdm
from time import sleep
from Channel import Channels
from Receiver import Receiver
from Sender import Sender
import matplotlib.pyplot as plt
from dbg_print import dbg_print

state_map = {"DWELL": 0, "SWITCH": 1, "SCHEDULE": 2, "SWITCH_TO_SCHEDULE": 3}

# "R1-polling-R2-scheduling"
# or "R1-Rn-both-scheduling-and-polling"
# or "R1-Rn-polling"

cur_sim_mode = "R1-Rn-both-scheduling-and-polling"
# cur_sim_mode = "R1-polling-R2-scheduling"
# cur_sim_mode = "R1-polling-R2-limited-polling"
# cur_sim_mode = "R1-Rn-polling"

OUTPUT_DATA_MODE = "CSV"  # "CSV" or "TERMINAL"
# OUTPUT_DATA_MODE = "TERMINAL"  # "CSV" or "TERMINAL"


class Simulator:

    def __init__(self, num_senders=15):
        self.cur_timestep = 0  # ms

        self.num_channels = 40
        self.num_receivers = 2
        self.num_senders = num_senders
        channels_per_receiver = self.num_channels // self.num_receivers

        self.uni_sender_info = {}  # 共享发送者信息
        self.uni_senders_channel_index = []  # 共享发送者信道索引

        self.channels = Channels(num_channels=self.num_channels)

        self.recvers = [
            Receiver(
                channels=(
                    self.channels.channels[
                        i * channels_per_receiver : (i + 1) * channels_per_receiver
                    ]
                    if cur_sim_mode == "R1-Rn-both-scheduling-and-polling"
                    else self.channels.channels
                ),
                index=i,
                channel_switch_time=5,
                channel_dwell_time=220,
                uni_sender_info=(
                    # 一个轮询一个调度时，共享发送者信息，否则各自维护
                    self.uni_sender_info
                    if cur_sim_mode == "R1-polling-R2-scheduling"
                    else None
                ),
                uni_senders_channel_index=(
                    # 仅在R1-polling-R2-limited-polling模式下共享发送者信道索引
                    self.uni_senders_channel_index
                    if cur_sim_mode == "R1-polling-R2-limited-polling"
                    else None
                ),
            )
            for i in range(self.num_receivers)
        ]

        self.senders: list[Sender] = []
        for i in range(num_senders):
            channel_index = random.randint(
                0, self.channels.channels.__len__() - 1
            )  # 频道索引是0~39
            sender = Sender(
                en=True,
                packet_id=f"SENDER_ID_{i}",
                interval=200,
                last_timestep=random.randint(0, 200),
                channel=self.channels.get_ch(channel_index),
                channel_index=channel_index,
            )
            self.senders.append(sender)

        self.state_records_per_recver = [[] for _ in range(self.num_receivers)]

    def run(self, step_limit=-1):
        senders = self.senders
        if step_limit > 0:
            pbar = tqdm(total=step_limit, desc=f"Sim(senders={self.num_senders})")
        while step_limit == -1 or self.cur_timestep < step_limit:
            # dbg_print(f"Simulator: timestep--------{self.cur_timestep}---------")
            for s in senders:
                s.packet_send(timestep=self.cur_timestep)
            for i, recver in enumerate(self.recvers):
                result = None
                if cur_sim_mode == "R1-polling-R2-scheduling":
                    result = (
                        recver.packet_recv(
                            cur_timestep=self.cur_timestep, just_polling=True
                        )
                        if i == 0
                        else recver.packet_schedule_recv(cur_timestep=self.cur_timestep)
                    )
                elif cur_sim_mode == "R1-Rn-polling":
                    result = recver.packet_recv(
                        cur_timestep=self.cur_timestep, just_polling=True
                    )
                elif cur_sim_mode == "R1-Rn-both-scheduling-and-polling":
                    result = recver.packet_recv(
                        cur_timestep=self.cur_timestep, just_polling=False
                    )
                elif cur_sim_mode == "R1-polling-R2-limited-polling":
                    result = recver.packet_recv(
                        cur_timestep=self.cur_timestep,
                        just_polling=True,
                        limited_polling=True if i == 1 else False,
                    )
                # 状态记录，用于显示时序图
                state = state_map[result[0]]
                self.state_records_per_recver[i].append((state, result[1]))

            self.channels.all_channel_lost()
            self.cur_timestep += 1
            if step_limit > 0:
                pbar.update(1)
        if step_limit > 0:
            pbar.close()
            # sleep(0.1)

    def summary(self):
        total_packets = 0
        received = 0
        losted = 0
        for ch in self.channels.channels:
            received += ch.packet_recved
            losted += ch.packet_losted
        total_packets = received + losted
        lost_rate = (losted / total_packets * 100) if total_packets > 0 else 0
        print(f"\nSimulation result:")
        print(f"    Total packets: {total_packets}")
        print(f"    Received     : {received}")
        print(f"    Lost         : {losted}")
        print(f"    Lost rate    : {lost_rate:.2f}%")

        print("\nPer-channel details:")
        for i, ch in enumerate(self.channels.channels):
            ch_total = ch.packet_recved + ch.packet_losted
            ch_lost_rate = ((ch.packet_losted / ch_total) * 100) if ch_total > 0 else 0
            print(
                f"  Channel {i}: total={ch_total}, received={ch.packet_recved}, lost={ch.packet_losted}, lost rate={ch_lost_rate:.2f}%"
            )

        sender_infos = []
        for recver in self.recvers:
            sender_infos.extend(recver.senders_info.values())
        column_labels = [
            "id",
            "last_sent_timestep",
            "send_times",
            "last_interval",
            "next_send_timestep",
            "channel_index",
        ]
        table_data = [
            [
                info.id,
                info.last_sent_timestep,
                str(info.send_times),
                f"{info.last_interval:.2f}",
                str(info.next_send_timestep),
                str(info.channel_index),
            ]
            for info in sender_infos
        ]
        md_filename = "./sender_info.md"
        with open(md_filename, "w", encoding="utf-8") as f:
            # 表头
            f.write("| " + " | ".join(column_labels) + " |\n")
            f.write("|" + "|".join(["---"] * len(column_labels)) + "|\n")
            # 每一行
            for row in table_data:
                f.write("| " + " | ".join(str(item) for item in row) + " |\n")

        for i, state_records in enumerate(self.state_records_per_recver):
            time_list = list(range(len(state_records)))
            states = []
            recved_idx, not_recved_idx = [], []
            for j, (s, flag) in enumerate(state_records):
                states.append(s)
                (recved_idx if flag else not_recved_idx).append(j)

            plt.figure(figsize=(14, 4))
            plt.plot(
                [time_list[i] for i in not_recved_idx],
                [states[i] for i in not_recved_idx],
                linestyle="None",
                marker="o",
                markersize=4,
                color="C0",
                label=f"Normal {i}",
            )
            plt.plot(
                [time_list[i] for i in recved_idx],
                [states[i] for i in recved_idx],
                linestyle="None",
                marker="o",
                markersize=3,
                color="red",
                label=f"RECVED {i}",
            )

            plt.yticks(
                [0, 1, 2, 3], ["DWELL", "SWITCH", "SCHEDULE", "SWITCH_TO_SCHEDULE"]
            )
            plt.xlabel("Timestep (ms)")
            plt.ylabel("State")
            plt.title(f"Receiver {i} State Sequence over Time")
            plt.grid(True)

            handles, labels = plt.gca().get_legend_handles_labels()
            by_label = dict(zip(labels, handles))  # 保证每个label唯一，后面的覆盖前面
            plt.legend(by_label.values(), by_label.keys())

            plt.tight_layout()
        plt.show()
        print("")

    def append_results_to_csv(self, filename="sim_result.csv"):
        # 1. 总体数据统计
        total_packets = 0
        received = 0
        losted = 0
        for ch in self.channels.channels:
            received += ch.packet_recved
            losted += ch.packet_losted
        total_packets = received + losted
        lost_rate = (losted / total_packets * 100) if total_packets > 0 else 0
        # 2. 按信道统计
        channel_rows = []
        for i, ch in enumerate(self.channels.channels):
            ch_total = ch.packet_recved + ch.packet_losted
            ch_lost_rate = ((ch.packet_losted / ch_total) * 100) if ch_total > 0 else 0
            channel_rows.append(
                [
                    i,
                    ch_total,
                    ch.packet_recved,
                    ch.packet_losted,
                    f"{ch_lost_rate:.2f}%",
                ]
            )
        # 3. 文件是否已存在，决定是否写入表头
        file_exists = os.path.isfile(filename)
        # 4. 写CSV
        with open(filename, "a", newline="", encoding="utf-8") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(
                [self.num_senders, total_packets, received, losted, f"{lost_rate:.2f}%"]
            )


if __name__ == "__main__":
    if OUTPUT_DATA_MODE == "TERMINAL":
        sim = Simulator()
        try:
            sim.run()
            sim.summary()
        except KeyboardInterrupt:
            sim.summary()

    elif OUTPUT_DATA_MODE == "CSV":
        CSV_FILENAME = "sim_result.csv"
        # 如果想每次都新建CSV（可注释下一行），否则默认每次都在同一个csv追加
        if os.path.exists(CSV_FILENAME):
            os.remove(CSV_FILENAME)
        total_steps = 30 * 60 * 1000

        for num_senders in range(1, 41):  # 1~40
            dbg_print(f"Running simulation with {num_senders} sender(s)...")
            sim = Simulator(num_senders=num_senders)
            sim.run(step_limit=total_steps)
            sim.append_results_to_csv(CSV_FILENAME)
        dbg_print("All simulations finished. Results written to", CSV_FILENAME)


# import numpy as np
# import matplotlib.pyplot as plt

# x_left = np.linspace(-5, -0.1, 500)
# x_right = np.linspace(1, 40, 500)
# y_right = 1 - 1 / x_right
# plt.plot(x_right, y_right, "b")
# plt.xlabel("x")
# plt.ylabel("y")
# plt.title("y = 1 - 1/x")
# plt.axvline(x=0, color="gray", linestyle="--", label="x=0")
# plt.grid(True)
# plt.legend()
# plt.show()
