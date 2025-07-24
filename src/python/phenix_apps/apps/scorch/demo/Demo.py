import datetime
#import sys
import os
#import time

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.common import logger, utils
from pathlib import Path

class Demo(ComponentBase):
    def __init__(self):
        ComponentBase.__init__(self, 'Demo')
        self.execute_stage()
    
    def start(self):
        logger.log('INFO', f'Starting user component: {self.name}')

        #check yaml to see if we want to include the year or not
        include_year = self.metadata.get('include_year', None)
        with open(os.path.join(self.base_dir, f'demo.txt')) as f:
            #if include_year, write current time with year. if not include_year, write current time without year
            if include_year:
                f.write(f'Current time: {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\n')
            else:
                f.write(f'Current time: {datetime.datetime.now().strftime("%m-%d %H:%M:%S")}\n')

    def stop(self):
        #nothing really needs to be stopped for this, we didn't start any services... but if we did, we could stop those here
        logger.log('INFO', f'Stopping user component: {self.name}')

def main():
    Demo()

if __name__ == '__main__':
    main()