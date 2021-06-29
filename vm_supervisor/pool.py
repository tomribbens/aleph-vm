import asyncio
import logging

from dataclasses import dataclass
from typing import Dict, Optional

from aleph_message.models import ProgramContent
from .conf import settings
from .models import VmHash
from .vm.firecracker_microvm import (
    AlephFirecrackerVM,
    AlephFirecrackerResources,
)

logger = logging.getLogger(__name__)


@dataclass
class StartedVM:
    vm: AlephFirecrackerVM
    program: ProgramContent
    timeout_task: Optional[asyncio.Task] = None


class VmPool:
    """Pool of VMs already started and used to decrease response time.
    After running, a VM is saved for future reuse from the same function during a
    configurable duration.

    The counter is used by the VMs to set their tap interface name and the corresponding
    IPv4 subnet.
    """

    counter: int  # Used to provide distinct ids to network interfaces
    _started_vms_cache: Dict[VmHash, StartedVM]

    def __init__(self):
        self.counter = settings.START_ID_INDEX
        self._started_vms_cache = {}

    async def create_a_vm(self, program: ProgramContent, vm_hash: VmHash) -> AlephFirecrackerVM:
        """Create a new Aleph Firecracker VM from an Aleph function message."""
        vm_resources = AlephFirecrackerResources(program)
        await vm_resources.download_all()
        self.counter += 1
        vm = AlephFirecrackerVM(
            vm_id=self.counter,
            vm_hash=vm_hash,
            resources=vm_resources,
            enable_networking=program.environment.internet,
            hardware_resources=program.resources,
        )
        try:
            await vm.setup()
            await vm.start()
            await vm.configure()
            await vm.start_guest_api()

            return vm
        except Exception:
            await vm.teardown()
            raise

    async def get(self, vm_hash: VmHash) -> Optional[AlephFirecrackerVM]:
        return self._started_vms_cache.get(vm_hash)

    async def get_or_create(self, program: ProgramContent, vm_hash: VmHash) -> AlephFirecrackerVM:
        """Returns a VM. Creates it if not already running."""
        started_vm = self._started_vms_cache.get(vm_hash)
        # if started_vm and started_vm.program == ProgramContent:
        if started_vm:
            return started_vm.vm
        else:
            return await self.create_a_vm(program=program, vm_hash=vm_hash)

    def keep_running(
        self, vm: AlephFirecrackerVM, program: ProgramContent, timeout: float = 1.0
    ) -> None:
        """Keep a VM running for `timeout` seconds."""

        if vm.vm_hash in self._started_vms_cache:
            logger.warning("VM already in keep_running, not caching")
            self.extend(vm.vm_hash, timeout)
            return

        started_vm = StartedVM(vm=vm, program=program)
        self._started_vms_cache[vm.vm_hash] = started_vm

        loop = asyncio.get_event_loop()
        started_vm.timeout_task = loop.create_task(self.expire(vm, timeout))

    def extend(self, vm_hash: VmHash, timeout: float = 1.0) -> None:
        started_vm = self._started_vms_cache[vm_hash]
        loop = asyncio.get_event_loop()
        new_timeout_task = loop.create_task(self.expire(started_vm.vm, timeout))
        started_vm.timeout_task.cancel()
        started_vm.timeout_task = new_timeout_task

    async def expire(
        self, vm: AlephFirecrackerVM, timeout: float
    ) -> None:
        """Coroutine that will stop the VM after 'timeout' seconds."""
        await asyncio.sleep(timeout)
        assert self._started_vms_cache[vm.vm_hash].vm is vm
        del self._started_vms_cache[vm.vm_hash]
        await vm.teardown()
