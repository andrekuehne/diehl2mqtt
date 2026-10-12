from dataclasses import replace
import sys
import time
from watermeter.mqtt import Publisher
from watermeter.settings import Settings
p = Publisher(replace(Settings(), mqtt=True, host="127.0.0.1", port=int(sys.argv[1])))
p.set_alive(True)
p.start()
while True:
    time.sleep(0.1)
