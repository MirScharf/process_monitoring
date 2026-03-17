#!/usr/bin/env python3
import math
import time


def busy_loop(seconds: float) -> None:
    end = time.time() + seconds
    value = 0.0
    while time.time() < end:
        value += math.sqrt(12345.6789)
    _ = value


if __name__ == "__main__":
    print("Python demo process started. Press Ctrl+C to stop.")
    while True:
        busy_loop(0.8)
        time.sleep(0.2)
