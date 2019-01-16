"""
Explicit tests for queue manipulation.
"""

import time

import pytest

import qcfractal.interface as portal
from qcfractal import testing, queue, FractalServer
from qcfractal.testing import reset_server_database, test_server
from qcfractal.testing import dask_server_fixture as compute_manager_fixture


@pytest.fixture(scope="module")
def compute_manager_fixture(test_server):

    client = portal.FractalClient(test_server)

    with testing.fireworks_quiet_lpad() as lpad:

        yield client, test_server, lpad


@testing.using_rdkit
def test_queue_manager_single(compute_manager_fixture):
    client, server, lpad = compute_manager_fixture
    reset_server_database(server)

    manager = queue.QueueManager(client, lpad)

    # Add compute
    hooh = portal.data.get_molecule("hooh.json")
    ret = client.add_compute("rdkit", "UFF", "", "energy", None, [hooh.to_json()], tag="other")

    # Force manager compute and get results
    manager.await_results()
    ret = client.get_results()
    assert len(ret) == 1


@testing.using_rdkit
def test_queue_manager_single_tags(compute_manager_fixture):
    client, server, lpad = compute_manager_fixture
    reset_server_database(server)

    manager_stuff = queue.QueueManager(client, lpad, queue_tag="stuff")
    manager_other = queue.QueueManager(client, lpad, queue_tag="other")

    # Add compute
    hooh = portal.data.get_molecule("hooh.json")
    ret = client.add_compute("rdkit", "UFF", "", "energy", None, [hooh.to_json()], tag="other")

    # Computer with the incorrect tag
    manager_stuff.await_results()
    ret = client.get_results()
    assert len(ret) == 0

    # Computer with the correct tag
    manager_other.await_results()
    ret = client.get_results()
    assert len(ret) == 1

    # Check the logs to make sure
    manager_logs = server.storage.get_managers({})["data"]
    assert len(manager_logs) == 2

    stuff_log = next(x for x in manager_logs if x["tag"] == "stuff")
    assert stuff_log["submitted"] == 0

    other_log = next(x for x in manager_logs if x["tag"] == "other")
    assert other_log["submitted"] == 1
    assert other_log["completed"] == 1


@testing.using_rdkit
def test_queue_manager_shutdown(compute_manager_fixture):
    """Tests to ensure tasks are returned to queue when the manager shuts down
    """
    client, server, lpad = compute_manager_fixture
    reset_server_database(server)

    manager = queue.QueueManager(client, lpad)

    hooh = portal.data.get_molecule("hooh.json")
    ret = client.add_compute("rdkit", "UFF", "", "energy", None, [hooh.to_json()], tag="other")

    # Pull job to manager and shutdown
    manager.update()
    assert len(manager.list_current_tasks()) == 1
    assert manager.shutdown()["nshutdown"] == 1

    sman = server.list_managers(name=manager.name())
    assert len(sman) == 1
    assert sman[0]["status"] == "INACTIVE"

    # Boot new manager and await results
    manager = queue.QueueManager(client, lpad)
    manager.await_results()
    ret = client.get_results()
    assert len(ret) == 1


def test_queue_manager_heartbeat():
    """Tests to ensure tasks are returned to queue when the manager shuts down
    """

    with testing.fireworks_quiet_lpad() as lpad:
        with testing.loop_in_thread() as loop:

            # Build server, manually handle IOLoop (no start/stop needed)
            server = FractalServer(
                port=testing.find_open_port(),
                storage_project_name="heartbeat_checker",
                loop=loop,
                ssl_options=False,
                heartbeat_frequency=0.1)

            # Clean and re-init the database
            testing.reset_server_database(server)

            client = portal.FractalClient(server)
            manager = queue.QueueManager(client, lpad)

            sman = server.list_managers(name=manager.name())
            assert len(sman) == 1
            assert sman[0]["status"] == "ACTIVE"

            # Make sure interval exceeds heartbeat time
            time.sleep(1)
            server.check_manager_heartbeats()

            sman = server.list_managers(name=manager.name())
            assert len(sman) == 1
            assert sman[0]["status"] == "INACTIVE"