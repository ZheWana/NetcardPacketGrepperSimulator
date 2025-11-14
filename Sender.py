from Channel import Channel
from Packet import Packet
from dbg_print import dbg_print


class Sender:
    """
    packet sender
    """

    def __init__(
        self,
        en: bool,
        packet_id: str,
        interval: int,
        last_timestep: int,
        channel: Channel,
        channel_index: int,
    ):
        self.en = en
        self.packet_id = packet_id
        self.interval = interval
        self.last_timestep = last_timestep
        self.channel: Channel = channel
        self.channel_index = channel_index
        dbg_print(f"Sender {self.packet_id}: Created in channel {self.channel_index}")
        pass

    def packet_send(self, timestep: int, x=0, y=0):
        if self.en:
            if timestep - self.last_timestep > self.interval:
                self.last_timestep = timestep
                p = Packet(self.packet_id, x, y)
                self.channel.packet_append(p)
                dbg_print(
                    f"Sender {self.packet_id}: Send 1 Packet to channel {self.channel_index}"
                )
                return p
            else:
                # dbg_print("Sender: in interval")
                pass
        else:
            dbg_print(f"Sender {self.packet_id}: closed")
