import time

from cellaserv.service import Service

class DateService(Service):

    service_name = "date"

    @Service.action
    def time(self):
        return int(time.time())

    @Service.event
    def kill(self):
        import sys
        sys.exit(0)

def main():
    date_service = DateService()
    date_service.run()

if __name__ == "__main__":
    main()
