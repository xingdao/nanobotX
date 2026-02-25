"""Cron service for scheduling agent tasks."""

import asyncio
import fcntl
import json
import os
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Coroutine

from loguru import logger

from nanobot.cron.types import CronJob, CronJobState, CronPayload, CronSchedule, CronStore

# 基础心跳间隔（毫秒） - 即使没有定时任务也保持定时器活跃
HEARTBEAT_INTERVAL_MS = 1200000  # 20分钟


def _now_ms() -> int:
    return int(time.time() * 1000)


@contextmanager
def _with_exclusive_file_lock(file_path: Path):
    """获取文件的独占锁（跨进程安全）。"""
    fd = None
    start_time = time.time()
    try:
        fd = os.open(file_path, os.O_RDWR | os.O_CREAT)
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        if fd:
            lock_duration = time.time() - start_time
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
            logger.debug(f"Lock released for {file_path} (held for {lock_duration:.3f}s)")


def _compute_next_run(schedule: CronSchedule, now_ms: int) -> int | None:
    """Compute next run time in ms."""
    if schedule.kind == "at":
        return schedule.at_ms if schedule.at_ms and schedule.at_ms > now_ms else None
    
    if schedule.kind == "every":
        if not schedule.every_ms or schedule.every_ms <= 0:
            return None
        # Next interval from now
        return now_ms + schedule.every_ms
    
    if schedule.kind == "cron" and schedule.expr:
        try:
            from croniter import croniter
            cron = croniter(schedule.expr, time.time())
            next_time = cron.get_next()
            return int(next_time * 1000)
        except Exception:
            return None
    
    return None


class CronService:
    """Service for managing and executing scheduled jobs."""
    
    def __init__(
        self,
        store_path: Path,
        on_job: Callable[[CronJob], Coroutine[Any, Any, str | None]] | None = None
    ):
        self.store_path = store_path
        self.on_job = on_job  # Callback to execute job, returns response text
        self._store: CronStore | None = None
        self._timer_task: asyncio.Task | None = None
        self._running = False
    
    def _load_store_from_file(self) -> tuple[CronStore, int]:
        """从文件加载存储并返回（存储对象，文件版本）。"""
        start_time = time.time()

        if not self.store_path.exists():
            return CronStore(), 1

        try:
            # TODO 编码
            with open(self.store_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            jobs = []
            for j in data.get("jobs", []):
                jobs.append(CronJob(
                    id=j["id"],
                    name=j["name"],
                    enabled=j.get("enabled", True),
                    schedule=CronSchedule(
                        kind=j["schedule"]["kind"],
                        at_ms=j["schedule"].get("atMs"),
                        every_ms=j["schedule"].get("everyMs"),
                        expr=j["schedule"].get("expr"),
                        tz=j["schedule"].get("tz"),
                    ),
                    payload=CronPayload(
                        kind=j["payload"].get("kind", "agent_turn"),
                        message=j["payload"].get("message", ""),
                        deliver=j["payload"].get("deliver", False),
                        channel=j["payload"].get("channel"),
                        to=j["payload"].get("to"),
                    ),
                    state=CronJobState(
                        next_run_at_ms=j.get("state", {}).get("nextRunAtMs"),
                        last_run_at_ms=j.get("state", {}).get("lastRunAtMs"),
                        last_status=j.get("state", {}).get("lastStatus"),
                        last_error=j.get("state", {}).get("lastError"),
                    ),
                    created_at_ms=j.get("createdAtMs", 0),
                    updated_at_ms=j.get("updatedAtMs", 0),
                    delete_after_run=j.get("deleteAfterRun", False),
                ))
            store = CronStore(version=data.get("version", 1), jobs=jobs)
            version = data.get("version", 1)
            load_duration = time.time() - start_time
            logger.debug(f"Store loaded from {self.store_path}: version={version}, jobs={len(jobs)}, duration={load_duration:.3f}s")
            return store, version
        except Exception as e:
            logger.warning(f"Failed to load cron store: {e}")
            load_duration = time.time() - start_time
            return CronStore(), 1

    def _save_store_to_file_no_lock(self, store: CronStore) -> None:
        """保存存储到文件（不带文件锁，调用者需确保已持有锁）。"""
        logger.debug(f"Saving store to {self.store_path} (no lock): version={store.version}, jobs={len(store.jobs)}")
        start_time = time.time()
        self.store_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "version": store.version,
            "jobs": [
                {
                    "id": j.id,
                    "name": j.name,
                    "enabled": j.enabled,
                    "schedule": {
                        "kind": j.schedule.kind,
                        "atMs": j.schedule.at_ms,
                        "everyMs": j.schedule.every_ms,
                        "expr": j.schedule.expr,
                        "tz": j.schedule.tz,
                    },
                    "payload": {
                        "kind": j.payload.kind,
                        "message": j.payload.message,
                        "deliver": j.payload.deliver,
                        "channel": j.payload.channel,
                        "to": j.payload.to,
                    },
                    "state": {
                        "nextRunAtMs": j.state.next_run_at_ms,
                        "lastRunAtMs": j.state.last_run_at_ms,
                        "lastStatus": j.state.last_status,
                        "lastError": j.state.last_error,
                    },
                    "createdAtMs": j.created_at_ms,
                    "updatedAtMs": j.updated_at_ms,
                    "deleteAfterRun": j.delete_after_run,
                }
                for j in store.jobs
            ]
        }

        self.store_path.write_text(json.dumps(data, indent=2), encoding='utf-8')

    def _save_store_to_file(self, store: CronStore) -> None:
        """保存存储到文件（带文件锁）。"""
        logger.debug(f"Saving store to {self.store_path} (with lock): version={store.version}, jobs={len(store.jobs)}")
        with _with_exclusive_file_lock(self.store_path):
            self._save_store_to_file_no_lock(store)

    # TODO 看使用
    def _load_store(self) -> CronStore:
        """Load jobs from disk (with memory caching)."""
        if self._store:
            logger.debug("Loading store from memory cache")
            return self._store

        # 从文件加载，不带锁（读取操作允许并发）
        store, version = self._load_store_from_file()
        store.version = version  # 确保存储版本与文件一致
        self._store = store
        logger.debug(f"Store loaded into memory cache: version={version}, jobs={len(store.jobs)}")
        return self._store
    
    def _save_store(self) -> None:
        """Save jobs to disk (with file lock)."""
        if not self._store:
            return
        self._save_store_to_file(self._store)
    
    async def start(self) -> None:
        """Start the cron service."""
        logger.info("Starting cron service")
        self._running = True
        self._load_store()
        self._recompute_next_runs()
        self._save_store()
        self._arm_timer()
        logger.info(f"Cron service started with {len(self._store.jobs if self._store else [])} jobs")
    
    def stop(self) -> None:
        """Stop the cron service."""
        logger.info("Stopping cron service")
        self._running = False
        if self._timer_task:
            self._timer_task.cancel()
            self._timer_task = None
            logger.debug("Timer task cancelled")
    
    def _merge_stores(self, file_store: CronStore) -> None:
        """合并文件存储和内存存储。
        任务定义（id、name、schedule、payload、enabled等）以文件为准。
        任务状态（state对象）以内存为准（如果任务存在）。
        """
        if not self._store:
            self._store = file_store
            return

        # 构建内存任务映射（ID -> 完整任务对象）
        memory_job_map = {job.id: job for job in self._store.jobs}

        # 对于文件中的每个任务
        merged_count = 0
        for file_job in file_store.jobs:
            if file_job.id in memory_job_map:
                memory_job = memory_job_map[file_job.id]
                # 保留内存中的任务状态
                file_job.state = memory_job.state
                merged_count += 1
                logger.debug(f"Merged job '{file_job.name}' (id={file_job.id}): kept state from memory")
                # 注意：next_run_at_ms可能基于旧的schedule，但_recompute_next_runs()会重新计算
                # last_run_at_ms、last_status、last_error等历史状态保持不变

        self._store = file_store

    def _recompute_next_runs(self) -> None:
        """Recompute next run times for all enabled jobs."""
        if not self._store:
            return
        now = _now_ms()

        recomputed_count = 0
        for job in self._store.jobs:
            if job.enabled:
                old_next_run = job.state.next_run_at_ms
                job.state.next_run_at_ms = _compute_next_run(job.schedule, now)
                if old_next_run != job.state.next_run_at_ms:
                    recomputed_count += 1

        logger.debug(f"Recomputed next runs for {recomputed_count} enabled jobs")
    
    def _get_next_wake_ms(self) -> int | None:
        """Get the earliest next run time across all jobs."""
        if not self._store:
            return None
        times = [j.state.next_run_at_ms for j in self._store.jobs
                 if j.enabled and j.state.next_run_at_ms]
        next_wake = min(times) if times else None
        logger.debug(f"Next wake time calculation: found {len(times)} scheduled times, next wake={next_wake}")
        return next_wake
    
    def _arm_timer(self) -> None:
        """安排下一个定时器触发（带基础心跳）。"""
        if self._timer_task:
            self._timer_task.cancel()

        next_wake = self._get_next_wake_ms()
        now_ms = _now_ms()

        # 如果没有定时任务，使用基础心跳间隔
        if not next_wake:
            delay_ms = HEARTBEAT_INTERVAL_MS
        else:
            # 计算到下一个任务的时间
            delay_ms = max(0, next_wake - now_ms)
            # 确保不超过最大心跳间隔的5倍
            if delay_ms > HEARTBEAT_INTERVAL_MS * 5:
                delay_ms = HEARTBEAT_INTERVAL_MS

        if not self._running:
            logger.debug("Service not running, skipping timer arming")
            return

        delay_s = delay_ms / 1000

        async def tick():
            await asyncio.sleep(delay_s)
            if self._running:
                await self._on_timer()

        self._timer_task = asyncio.create_task(tick())
    
    async def _on_timer(self) -> None:
        """处理定时器触发 - 重新加载文件并执行到期任务。"""
        # 重新加载文件并检查版本
        old_version = self._store.version if self._store else None
        file_store, file_version = self._load_store_from_file()

        # 检查版本变化
        version_changed = old_version != file_version

        if version_changed:
            logger.debug(f"Version changed, merging stores. Memory jobs={len(self._store.jobs) if self._store else 0}, file jobs={len(file_store.jobs)}")
            # 合并文件中的任务定义和内存中的任务状态
            self._merge_stores(file_store)
            self._store.version = file_version
            # 重新计算下次运行时间
            self._recompute_next_runs()
            # 保存到文件（更新版本）
            self._save_store_to_file(self._store)
        elif self._store:
            # 版本未变，直接使用内存缓存
            file_store = self._store

        # 执行到期jobs（基于当前store）
        now = _now_ms()
        due_jobs = [
            j for j in file_store.jobs
            if j.enabled and j.state.next_run_at_ms and now >= j.state.next_run_at_ms
        ]
        logger.debug(f"Found {len(due_jobs)} due jobs to execute")

        executed_jobs = False  # 记录是否有任务被执行
        for job in due_jobs:
            await self._execute_job(job)
            executed_jobs = True

        # 保存状态更新（仅在版本变化或有任务执行时）
        if self._store and (version_changed or executed_jobs):
            self._save_store()

        # 安排下一次定时器
        self._arm_timer()
    
    async def _execute_job(self, job: CronJob) -> None:
        """Execute a single job."""
        start_ms = _now_ms()
        logger.info(f"Cron: executing job '{job.name}' ({job.id})")
        
        try:
            response = None
            if self.on_job:
                response = await self.on_job(job)
            
            job.state.last_status = "ok"
            job.state.last_error = None
            logger.info(f"Cron: job '{job.name}' completed")
            
        except Exception as e:
            job.state.last_status = "error"
            job.state.last_error = str(e)
            logger.error(f"Cron: job '{job.name}' failed: {e}")

        job.state.last_run_at_ms = start_ms
        job.updated_at_ms = _now_ms()
        
        # Handle one-shot jobs
        if job.schedule.kind == "at":
            if job.delete_after_run:
                self._store.jobs = [j for j in self._store.jobs if j.id != job.id]
            else:
                logger.debug(f"One-shot job '{job.name}' disabled after run")
                job.enabled = False
                job.state.next_run_at_ms = None
        else:
            # Compute next run
            next_run = _compute_next_run(job.schedule, _now_ms())
            job.state.next_run_at_ms = next_run
    
    # ========== Public API ==========
    
    def list_jobs(self, include_disabled: bool = False) -> list[CronJob]:
        """List jobs.

        Args:
            include_disabled: If True, includes disabled jobs. Default is False (only enabled jobs)."""
        store = self._load_store()
        jobs = store.jobs if include_disabled else [j for j in store.jobs if j.enabled]
        return sorted(jobs, key=lambda j: j.state.next_run_at_ms or float('inf'))
    
    def add_job(
        self,
        name: str,
        schedule: CronSchedule,
        message: str,
        deliver: bool = False,
        channel: str | None = None,
        to: str | None = None,
        delete_after_run: bool = False,
    ) -> CronJob:
        """添加新job（带文件锁）。"""
        logger.info(f"Adding job: name='{name}', schedule={schedule.kind}, deliver={deliver}")
        with _with_exclusive_file_lock(self.store_path):
            # 加载当前文件状态
            file_store, version = self._load_store_from_file()
            now = _now_ms()

            job = CronJob(
                id=str(uuid.uuid4())[:8],
                name=name,
                enabled=True,
                schedule=schedule,
                payload=CronPayload(
                    kind="agent_turn",
                    message=message,
                    deliver=deliver,
                    channel=channel,
                    to=to,
                ),
                state=CronJobState(next_run_at_ms=_compute_next_run(schedule, now)),
                created_at_ms=now,
                updated_at_ms=now,
                delete_after_run=delete_after_run,
            )

            file_store.jobs.append(job)
            file_store.version = version + 1

            # 保存到文件（已持有锁，使用无锁版本）
            self._save_store_to_file_no_lock(file_store)

            # 更新内存缓存
            self._store = file_store

        # 重新安排定时器（无锁）
        self._arm_timer()

        logger.info(f"Cron: added job '{name}' ({job.id})")
        return job
    
    def remove_job(self, job_id: str) -> bool:
        """移除job（带文件锁）。"""
        logger.info(f"Removing job: id={job_id}")
        with _with_exclusive_file_lock(self.store_path):
            # 加载当前文件状态
            file_store, version = self._load_store_from_file()
            before = len(file_store.jobs)
            file_store.jobs = [j for j in file_store.jobs if j.id != job_id]
            removed = len(file_store.jobs) < before

            if removed:
                file_store.version = version + 1
                logger.debug(f"Version incremented to {file_store.version}")
                # 保存到文件（已持有锁，使用无锁版本）
                self._save_store_to_file_no_lock(file_store)
                # 更新内存缓存
                self._store = file_store

        if removed:
            # 重新安排定时器（无锁）
            self._arm_timer()
            logger.info(f"Cron: removed job {job_id}")

        return removed
    
    def enable_job(self, job_id: str, enabled: bool = True) -> CronJob | None:
        """启用或禁用job（带文件锁）。"""
        logger.info(f"Setting job enabled: id={job_id}, enabled={enabled}")
        with _with_exclusive_file_lock(self.store_path):
            # 加载当前文件状态
            file_store, version = self._load_store_from_file()
            for job in file_store.jobs:
                if job.id == job_id:
                    job.enabled = enabled
                    job.updated_at_ms = _now_ms()
                    if enabled:
                        job.state.next_run_at_ms = _compute_next_run(job.schedule, _now_ms())
                    else:
                        job.state.next_run_at_ms = None
                    # 递增版本
                    file_store.version = version + 1
                    logger.debug(f"Version incremented to {file_store.version}, next_run_at_ms={job.state.next_run_at_ms}")
                    # 保存到文件（已持有锁，使用无锁版本）
                    self._save_store_to_file_no_lock(file_store)
                    # 更新内存缓存
                    self._store = file_store

                    # 重新安排定时器（无锁）
                    self._arm_timer()
                    return job
        return None
    
    async def run_job(self, job_id: str, force: bool = False) -> bool:
        """手动运行job（带文件锁）。"""
        logger.info(f"Manually running job: id={job_id}, force={force}")
        with _with_exclusive_file_lock(self.store_path):
            # 加载当前文件状态
            file_store, version = self._load_store_from_file()
            for job in file_store.jobs:
                if job.id == job_id:
                    if not force and not job.enabled:
                        logger.warning(f"Job {job_id} is disabled and force={force}, skipping")
                        return False
                    await self._execute_job(job)
                    # 递增版本
                    file_store.version = version + 1
                    # 保存到文件（已持有锁，使用无锁版本）
                    self._save_store_to_file_no_lock(file_store)
                    # 更新内存缓存
                    self._store = file_store

                    # 重新安排定时器（无锁）
                    self._arm_timer()
                    return True
        return False
    
    def status(self) -> dict:
        """Get service status."""
        store = self._load_store()
        return {
            "enabled": self._running,
            "jobs": len(store.jobs),
            "next_wake_at_ms": self._get_next_wake_ms(),
        }
