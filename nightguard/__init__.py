import logging

logging.basicConfig(format='%(asctime)s - %(message)s', datefmt='%d-%b-%y %H:%M:%S', level=logging.INFO)
logging.info('test from init')

from pathlib import Path
PAK_DIR = Path(__file__).parent.parent.absolute().resolve()
print(f'Package Dir: {PAK_DIR}')

from .toNight import Tonight
from .mt5Api import MT5Api
