import asyncio
import time

from hhart.websocket_publisher import WebSocketPublisher

# Under the 10 s close timeout, Over SEND_TIMEOUT_S
SLOW_S = 3.0


class Recording:
    def __init__(self):
        self.sent = []

    async def send(self, payload):
        self.sent.append(payload)


class Hanging:
    async def send(self, payload):
        await asyncio.sleep(3600)


async def publish_promptly(pub, message):
    try:
        await asyncio.wait_for(pub.publish(message), SLOW_S)
    except asyncio.TimeoutError:
        raise AssertionError(f"publish was still blocked after {SLOW_S} s")


def test_one_hanging_client_does_not_delay_the_others():
    pub = WebSocketPublisher()
    good, bad = Recording(), Hanging()
    pub.add(good)
    pub.add(bad)

    start = time.monotonic()
    asyncio.run(publish_promptly(pub, {"type": "imu"}))
    elapsed = time.monotonic() - start

    assert good.sent == ['{"type": "imu"}']
    assert elapsed < SLOW_S, f"publish blocked for {elapsed:.2f} s"


def test_a_client_that_times_out_is_dropped():
    pub = WebSocketPublisher()
    good, bad = Recording(), Hanging()
    pub.add(good)
    pub.add(bad)

    asyncio.run(publish_promptly(pub, {"type": "imu"}))

    assert pub.client_count == 1
    asyncio.run(publish_promptly(pub, {"type": "odometry"}))
    assert len(good.sent) == 2


def test_results_are_paired_with_the_clients_that_produced_them():
    pub = WebSocketPublisher()
    good, bad = Recording(), Hanging()
    pub.add(good)
    pub.add(bad)

    async def publish_while_a_client_joins():
        task = asyncio.ensure_future(publish_promptly(pub, {"type": "imu"}))
        await asyncio.sleep(0)
        pub.add(Recording())
        await task

    asyncio.run(publish_while_a_client_joins())

    assert good in pub._clients, "the healthy client was dropped"
    assert bad not in pub._clients, "the hanging client was kept"
