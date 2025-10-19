from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src.models.task import Task
from src.persistence.parameters_db import get_company_ids, get_scheduled_times
import logging

from datetime import datetime

from src.persistence.task_db import save_task
from src.service.ozon_service import OzonService

logger = logging.getLogger(__name__)


class ScedulerService:
    def __init__(self, ozon_servie: OzonService):
        self.scheduler = AsyncIOScheduler()
        self.ozon_service = ozon_servie
        self._is_running = False
        self.task = None

    async def get_scheduled_times(self) -> list[str]:
        return await get_scheduled_times()

    async def restart_scheduler(self):
        schedule = await self.get_scheduled_times()
        self.scheduler.remove_all_jobs()
        self._is_running = False
        for scheduled_times in schedule:
            hour, minute = map(int, scheduled_times.split(':'))
            self.scheduler.add_job(
                self.test_job,
                'cron',
                hour=hour,
                minute=minute,
                max_instances=1,
                name=f"price_change_{hour}_{minute}",
                coalesce=True
            )
        if schedule and self.scheduler.state == 0:
            self.scheduler.start()

    async def test_job(self):
        task = None
        if  self._is_running:
            logger.warning("job is already running skipping this one")
            return
        try:
            date = datetime.now().date()
            company_ids = await get_company_ids()
            for company_id in company_ids:
                try:
                    task = Task(name=company_id, status='getting prices')
                    await save_task(task)
                    await self.ozon_service.get_ozon_prices(date, company_id)
                    task.status = 'generating report'
                    await save_task(task)
                    await self.ozon_service.prepare_excel_report(date, company_id)
                    task.status = 'FINISHED'
                    await save_task(task)
                except Exception as e:
                    logger.exception(e)
                    if task:
                        task.status = "ERROR: " + str(e)
                        await save_task(task)
        finally:
            self._is_running = False
