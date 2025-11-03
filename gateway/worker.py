import os

import redis
from rq import Queue, Worker
from rq.connections import Connection

listen = ['default']

redis_url = os.getenv('REDIS_URL', 'redis://redis:6379/0')
conn = redis.from_url(redis_url)

if __name__ == '__main__':
    with Connection(conn):
        worker = Worker(map(Queue, listen))
        worker.work()
