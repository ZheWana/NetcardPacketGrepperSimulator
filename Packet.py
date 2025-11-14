class Packet():
    """
    packet to be sent and received
    """
    
    def __init__(self,packet_id:str,x=0,y=0):
        self.packet_id = packet_id
        self.x = x
        self.y = y