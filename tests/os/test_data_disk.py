"""Test OS API."""
from pathlib import PosixPath
from unittest.mock import patch

import pytest

from supervisor.core import Core
from supervisor.coresys import CoreSys
from supervisor.exceptions import HassOSDataDiskError
from supervisor.os.data_disk import Disk

from tests.common import mock_dbus_services
from tests.dbus_service_mocks.agent_datadisk import DataDisk as DataDiskService
from tests.dbus_service_mocks.base import DBusServiceMock
from tests.dbus_service_mocks.logind import Logind as LogindService

# pylint: disable=protected-access


@pytest.fixture(autouse=True)
async def add_unusable_drive(
    coresys: CoreSys,
    udisks2_services: dict[str, DBusServiceMock | dict[str, DBusServiceMock]],
):
    """Add mock drive with multiple partition tables for negative tests."""
    await mock_dbus_services(
        {
            "udisks2_block": [
                "/org/freedesktop/UDisks2/block_devices/multi_part_table1",
                "/org/freedesktop/UDisks2/block_devices/multi_part_table2",
            ],
            "udisks2_drive": "/org/freedesktop/UDisks2/drives/Test_Multiple_Partition_Tables_123456789",
        },
        coresys.dbus.bus,
    )

    udisks2_services["udisks2_manager"].block_devices = udisks2_services[
        "udisks2_manager"
    ].block_devices + [
        "/org/freedesktop/UDisks2/block_devices/multi_part_table1",
        "/org/freedesktop/UDisks2/block_devices/multi_part_table2",
    ]
    await coresys.dbus.udisks2.update()


async def tests_datadisk_current(coresys: CoreSys):
    """Test current datadisk."""
    assert coresys.os.datadisk.disk_used == Disk(
        vendor="",
        model="BJTD4R",
        serial="0x97cde291",
        id="BJTD4R-0x97cde291",
        size=31268536320,
        device_path=PosixPath("/dev/mmcblk1"),
        object_path="/org/freedesktop/UDisks2/drives/BJTD4R_0x97cde291",
    )


@pytest.mark.parametrize(
    "new_disk",
    ["/dev/sdaaaa", "/dev/mmcblk1", "Generic-Flash-Disk-61BCDDB6"],
    ids=["non-existent", "unavailable drive by path", "unavailable drive by id"],
)
async def test_datadisk_move_fail(coresys: CoreSys, new_disk: str):
    """Test datadisk move to non-existent or invalid devices."""
    coresys.os._available = True

    with pytest.raises(HassOSDataDiskError):
        await coresys.os.datadisk.migrate_disk(new_disk)


async def test_datadisk_list(coresys: CoreSys):
    """Test docker info api."""
    assert {drive.object_path for drive in coresys.dbus.udisks2.drives} == {
        "/org/freedesktop/UDisks2/drives/BJTD4R_0x97cde291",
        "/org/freedesktop/UDisks2/drives/Generic_Flash_Disk_61BCDDB6",
        "/org/freedesktop/UDisks2/drives/SSK_SSK_Storage_DF56419883D56",
        "/org/freedesktop/UDisks2/drives/Test_Multiple_Partition_Tables_123456789",
    }

    assert coresys.os.datadisk.available_disks == [
        Disk(
            vendor="SSK",
            model="SSK Storage",
            serial="DF56419883D56",
            id="SSK-SSK-Storage-DF56419883D56",
            size=250059350016,
            device_path=PosixPath("/dev/sda"),
            object_path="/org/freedesktop/UDisks2/drives/SSK_SSK_Storage_DF56419883D56",
        )
    ]


@pytest.mark.parametrize(
    "new_disk",
    ["SSK-SSK-Storage-DF56419883D56", "/dev/sda"],
    ids=["by drive id", "by device path"],
)
async def test_datadisk_migrate(
    coresys: CoreSys,
    all_dbus_services: dict[str, DBusServiceMock | dict[str, DBusServiceMock]],
    new_disk: str,
):
    """Test migrating data disk."""
    datadisk_service: DataDiskService = all_dbus_services["agent_datadisk"]
    datadisk_service.ChangeDevice.calls.clear()
    logind_service: LogindService = all_dbus_services["logind"]
    logind_service.Reboot.calls.clear()
    coresys.os._available = True

    with patch.object(Core, "shutdown") as shutdown:
        await coresys.os.datadisk.migrate_disk(new_disk)
        shutdown.assert_called_once()

    assert datadisk_service.ChangeDevice.calls == [("/dev/sda",)]
    assert logind_service.Reboot.calls == [(False,)]
