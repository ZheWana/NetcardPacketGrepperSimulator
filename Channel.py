from Packet import Packet


class Channel:
    def __init__(self, index):
        self.packets: list[Packet] = []
        self.listening: bool = False
        self.channel_index = index
        self.packet_sended = 0
        self.packet_recved = 0
        self.packet_losted = 0

    def listen(self):
        self.listening = True

    def quit_listen(self):
        self.listening = False

    def packet_append(self, p: Packet):
        self.packets.append(p)
        self.packet_sended += 1

    def packet_pop(self):
        if self.packets:
            self.packet_recved += 1
            return self.packets.pop(0)
        return None

    def packet_lost(self):
        for p in self.packets:
            self.packet_losted += 1
            return self.packets.pop(0)


class Channels:
    def __init__(self, num_channels=40):
        self.channels: list[Channel] = [Channel(i) for i in range(num_channels)]

    def all_channel_lost(self):
        for ch in self.channels:
            if not ch.listening:
                ch.packet_lost()

    def get_ch(self, channel_index):
        return self.channels[channel_index if 0 < channel_index < 40 else 0]

    pass
