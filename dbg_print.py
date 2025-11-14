DEBUG = False

def dbg_print(*args, **kwargs):
    if DEBUG:
        print(*args, **kwargs)
