from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src.models.task import Task
from src.persistence.parameters_db import get_company_ids, get_scheduled_times, get_wb_accounts
import logging

from datetime import datetime

from src.persistence.task_db import save_task
from src.service.ozon_service import OzonService
from src.service.wb_service import WbService

logger = logging.getLogger(__name__)


class ScedulerService:
    def __init__(self, ozon_servie: OzonService, wb_service: WbService):
        self.scheduler = AsyncIOScheduler()
        self.ozon_service = ozon_servie
        self.wb_service = wb_service
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
        if self._is_running:
            logger.warning("job is already running skipping this one")
            return
        self._is_running = True
        try:
            date = datetime.now().date()
            company_ids = await get_company_ids()
            if company_ids:
                try:
                    await self.ozon_service.api.open_browser()
                    try:
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
                        await self.ozon_service.api.close_browser()
                except Exception:
                    logger.exception("ozon collection failed")
            await self._collect_wb(date)
        except Exception:
            logger.exception("scheduled job failed")
        finally:
            self._is_running = False

    async def _collect_wb(self, collect_date):
        accounts = await get_wb_accounts()
        if not accounts:
            logger.info("no WB accounts configured, skipping WB collection")
            return
        for account in accounts:
            task_name = f"wb:{account.name}"
            if not account.token:
                task = Task(name=task_name, status="ERROR: WB API token is not configured")
                await save_task(task)
                continue
            task = Task(name=task_name, status="getting prices")
            await save_task(task)
            try:
                await self.wb_service.collect_prices(collect_date, account.name)
                task.status = "generating report"
                await save_task(task)
                await self.wb_service.prepare_excel_report(collect_date, account=account.name)
                task.status = "FINISHED"
                await save_task(task)
            except Exception as e:
                logger.exception(e)
                task.status = "ERROR: " + str(e)
                await save_task(task)
