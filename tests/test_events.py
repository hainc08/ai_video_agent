import asyncio

from app.events import EventHub


async def collect(subscription):
    return [event async for event in subscription]


async def test_every_subscriber_of_a_job_gets_its_events_in_order_until_the_channel_closes():
    hub = EventHub()
    first, second = hub.subscribe("job-1"), hub.subscribe("job-1")
    other = hub.subscribe("job-2")

    hub.publish("job-1", {"type": "update", "n": 1})
    hub.publish("job-1", {"type": "update", "n": 2})
    hub.publish("job-2", {"type": "update", "n": 9})
    hub.close("job-1")
    hub.close("job-2")

    expected = [{"type": "update", "n": 1}, {"type": "update", "n": 2}]
    assert await collect(first) == expected
    assert await collect(second) == expected
    assert await collect(other) == [{"type": "update", "n": 9}]


async def test_a_late_subscriber_only_sees_later_events():
    hub = EventHub()
    hub.publish("job-1", {"n": 1})
    late = hub.subscribe("job-1")
    hub.publish("job-1", {"n": 2})
    hub.close("job-1")

    assert await collect(late) == [{"n": 2}]


async def test_publishing_and_closing_without_subscribers_does_nothing():
    hub = EventHub()

    hub.publish("nobody", {"n": 1})
    hub.close("nobody")

    assert hub.subscriber_count("nobody") == 0


async def test_a_cancelled_subscription_is_forgotten_and_ends():
    hub = EventHub()
    subscription = hub.subscribe("job-1")
    assert hub.subscriber_count("job-1") == 1

    subscription.cancel()
    hub.publish("job-1", {"n": 1})

    assert hub.subscriber_count("job-1") == 0
    assert await asyncio.wait_for(collect(subscription), timeout=1) == []


async def test_a_waiting_subscriber_wakes_up_when_an_event_arrives():
    hub = EventHub()
    subscription = hub.subscribe("job-1")
    waiter = asyncio.create_task(collect(subscription))
    await asyncio.sleep(0.01)

    hub.publish("job-1", {"n": 1})
    hub.close("job-1")

    assert await asyncio.wait_for(waiter, timeout=1) == [{"n": 1}]
