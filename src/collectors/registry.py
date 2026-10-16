from src.collectors.getonboard import GetOnBoardCollector
from src.collectors.hacker_news import HackerNewsCollector
from src.collectors.himalayas import HimalayasCollector
from src.collectors.jobicy import JobicyCollector
from src.collectors.jooble import JoobleCollector
from src.collectors.remoteok import RemoteOKCollector
from src.collectors.the_muse import TheMuseCollector
from src.collectors.weworkremotely import WeWorkRemotelyCollector

COLLECTORS = {
    "remoteok": RemoteOKCollector,
    "getonboard": GetOnBoardCollector,
    "weworkremotely": WeWorkRemotelyCollector,
    "himalayas": HimalayasCollector,
    "jobicy": JobicyCollector,
    "the_muse": TheMuseCollector,
    "hacker_news": HackerNewsCollector,
    "jooble": JoobleCollector,
}
