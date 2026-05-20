import os
import time
import base64


def generate_random_id() -> str:
    ms = int(time.time() * 1000)
    rand = int.from_bytes(os.urandom(2), "big")  # 16 bits randomness
    value = (ms << 16) | rand
    return base64.urlsafe_b64encode(value.to_bytes(10, "big")).rstrip(b"=").decode()
