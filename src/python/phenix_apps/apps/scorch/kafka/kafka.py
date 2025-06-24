import json, itertools, threading, time, sys, csv, re

from phenix_apps.apps.scorch import ComponentBase
from phenix_apps.common import logger, utils
from kafka import KafkaConsumer
from kafka.errors import KafkaError
from datetime import datetime

class kafka(ComponentBase):
    def __init__(self):
        ComponentBase.__init__(self, 'kafka')
        self.execute_stage()
    
    #uses regular expressions to convert the time format in the tags to actually be a datetime object
    def parseTime(self, inTime):
        timeForm = r"datetime\.datetime\((\d+), (\d+), (\d+), (\d+), (\d+), (\d+), (\d+)\)"
        match = re.match(timeForm, inTime)
        if match:
            sections = list(map(int, match.groups()))
            return datetime(*sections)
        return None

    #converts a timestamp into the excel format for timestamps
    def timeConverter(self, inTime):
        #excel starts timestamps at 30th, Decemember, 1899
        startTime = datetime(1899, 12, 30)
        timeDiff =  inTime - startTime
        
        #convert to excel format
        newTime = timeDiff.days + (timeDiff.seconds + timeDiff.microseconds / 1_000_000) / 86400
        return newTime

    def start(self):
        logger.log('INFO', f'Starting user component: {self.name}')

        #get all variables from tags
        bootstrapServers = self.metadata.get("bootstrapServers", ["172.20.0.74:9092"])
        allScan = self.metadata.get("allScan", False)
        subscribeTags = self.metadata.get("subscribeTags", [])
        critLoad = self.metadata.get("critLoad", "").lower()
        mode = self.metadata.get("mode", "all data")
        substation =  self.metadata.get("substation", "")
        csvOut = self.metadata.get("csv", True)

        #kafka consumer
        consumer = KafkaConsumer(
            #bootstrap ip and port could probably be a variable in the future
            bootstrap_servers = bootstrapServers,
            auto_offset_reset='latest',
            enable_auto_commit=False,
            value_deserializer=lambda m: json.loads(m.decode('utf-8'))
        )

        #we either scan all data, or scan subscribed tags only
        if allScan:
            consumer.subscribe(pattern='.*')
        else:
            consumer.subscribe(subscribeTags)

        #store all relevant messages in this list
        relMes = []

        output_dir = self.base_dir
        os.makedirs(output_dir, exist_ok=True)

        all_keys = set()
        wrote_header = False

        try:
            #run the consumer, try to find all messages with the relevant tags
            if csvOut:
                with open(output_dir, 'out.csv', mode="a", newline="", encoding="utf-8") as file:
                    writer = None
                    while True:
                        for message in consumer:
                            data = message.value
                            if not isinstance(data, dict) and "timestamp" in data:
                                continue
                            
                            #parse the time and convert it to excel time
                            currTime = parseTime(data["timestamp"])
                            currTime = timeConverter(currTime)

                            #set the csv to use excel time instead of timestamps
                            data["timestamp"] = currTime
                            name = data.get("name", "").lower()

                            include = (
                                (mode == "all data") or
                                (mode == "critical load" and name == critLoad) or
                                (mode == "substation" and substation in name)
                            )

                            if include:
                                all_keys.update(data.keys())

                                if writer is None:
                                    writer = csv.DictWriter(file, fieldnames=sorted(all_keys), extrasaction='ignore')
                                    
                                    #check if the first line in the csv has been written yet, write it if not
                                    if not wrote_header:
                                        writer.writeheader()
                                        wrote_header = True

                                writer.writerow(data)
                                file.flush()
            else:
                with open(output_dir, 'out.txt', 'a', encoding='utf-8') as file:
                    while True:
                        for message in consumer:
                            data = message.value
                            if not isinstance(data, dict) and "timestamp" in data:
                                continue
                            
                            #parse the time and convert it to excel time
                            currTime = parseTime(data["timestamp"])
                            currTime = timeConverter(currTime)

                            #set the json file to use excel time instead of timestamps
                            data["timestamp"] = currTime
                            name = data.get("name", "").lower()

                            include = (
                                (mode == "all data") or
                                (mode == "critical load" and name == critLoad) or
                                (mode == "substation" and substation in name)
                            )

                            if include:
                                file.write(json.dumps(data) + "\n")
                                file.flush()

        except Exception as e:
            pass
        finally:
            consumer.close()

        logger.log('INFO', f'Configured user component: {self.name}')

    def stop(self):
        #it should run as long as the experiment runs, so I don't think anything needs to be here
        logger.log('INFO', f'Stopping user component: {self.name}')

    def cleanup(self):
        #no cleanup, currently it just makes and populates the one csv file
        logger.log('INFO', f'Cleaning up user component: {self.name}')

def main():
    kafka()
    
if __name__ == '__main__':
    main()
