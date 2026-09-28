from src.collectors.getonboard import GetOnBoardCollector
from src.collectors.remoteok import RemoteOKCollector
from src.collectors.weworkremotely import WeWorkRemotelyCollector

COLLECTORS = {
    "remoteok": RemoteOKCollector,
    "getonboard": GetOnBoardCollector,
    "weworkremotely": WeWorkRemotelyCollector,
}
