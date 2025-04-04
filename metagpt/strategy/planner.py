from __future__ import annotations

from typing import List

from metagpt.actions.ask_review import AskReview, ReviewConst
from metagpt.actions.write_plan import (
    WritePlan,
    precheck_update_plan_from_rsp,
    update_plan_from_rsp,
)
from metagpt.core.logs import logger
from metagpt.core.schema import Message, Plan, Task, TaskResult
from metagpt.core.strategy.planner import PLAN_STATUS, BasePlanner
from metagpt.core.utils.common import remove_comments
from metagpt.strategy.task_type import TaskType


class Planner(BasePlanner):
    async def update_plan(self, goal: str = "", max_tasks: int = 3, max_retries: int = 3):
        if goal:
            self.plan = Plan(goal=goal)

        plan_confirmed = False
        while not plan_confirmed:
            context = self.get_useful_memories()
            rsp = await WritePlan().run(context, max_tasks=max_tasks)
            self.working_memory.add(Message(content=rsp, role="assistant", cause_by=WritePlan))

            # precheck plan before asking reviews
            is_plan_valid, error = precheck_update_plan_from_rsp(rsp, self.plan)
            if not is_plan_valid and max_retries > 0:
                error_msg = f"The generated plan is not valid with error: {error}, try regenerating, remember to generate either the whole plan or the single changed task only"
                logger.warning(error_msg)
                self.working_memory.add(Message(content=error_msg, role="assistant", cause_by=WritePlan))
                max_retries -= 1
                continue

            _, plan_confirmed = await self.ask_review(trigger=ReviewConst.TASK_REVIEW_TRIGGER)

        update_plan_from_rsp(rsp=rsp, current_plan=self.plan)

        self.working_memory.clear()

    async def process_task_result(self, task_result: TaskResult):
        # ask for acceptance, users can other refuse and change tasks in the plan
        review, task_result_confirmed = await self.ask_review(task_result)

        if task_result_confirmed:
            # tick off this task and record progress
            await self.confirm_task(self.current_task, task_result, review)

        elif "redo" in review:
            # Ask the Role to redo this task with help of review feedback,
            # useful when the code run is successful but the procedure or result is not what we want
            pass  # simply pass, not confirming the result

        else:
            # update plan according to user's feedback and to take on changed tasks
            await self.update_plan()

    async def ask_review(
        self,
        task_result: TaskResult = None,
        auto_run: bool = None,
        trigger: str = ReviewConst.TASK_REVIEW_TRIGGER,
        review_context_len: int = 5,
    ):
        """
        Ask to review the task result, reviewer needs to provide confirmation or request change.
        If human confirms the task result, then we deem the task completed, regardless of whether the code run succeeds;
        if auto mode, then the code run has to succeed for the task to be considered completed.
        """
        auto_run = auto_run if auto_run is not None else self.auto_run
        if not auto_run:
            context = self.get_useful_memories()
            review, confirmed = await AskReview().run(
                context=context[-review_context_len:], plan=self.plan, trigger=trigger
            )
            if not confirmed:
                self.working_memory.add(Message(content=review, role="user", cause_by=AskReview))
            return review, confirmed
        confirmed = task_result.is_success if task_result else True
        return "", confirmed

    async def confirm_task(self, task: Task, task_result: TaskResult, review: str):
        task.update_task_result(task_result=task_result)
        self.plan.finish_current_task()
        self.working_memory.clear()

        confirmed_and_more = (
            ReviewConst.CONTINUE_WORDS[0] in review.lower() and review.lower() not in ReviewConst.CONTINUE_WORDS[0]
        )  # "confirm, ... (more content, such as changing downstream tasks)"
        if confirmed_and_more:
            self.working_memory.add(Message(content=review, role="user", cause_by=AskReview))
            await self.update_plan()

    def get_plan_status(self, exclude: List[str] = None) -> str:
        # prepare components of a plan status
        exclude = exclude or []
        exclude_prompt = "omit here"
        finished_tasks = self.plan.get_finished_tasks()
        code_written = [remove_comments(task.code) for task in finished_tasks]
        code_written = "\n\n".join(code_written)
        task_results = [task.result for task in finished_tasks]
        task_results = "\n\n".join(task_results)
        task_type_name = self.current_task.task_type
        task_type = TaskType.get_type(task_type_name)
        guidance = task_type.guidance if task_type else ""

        # combine components in a prompt
        prompt = PLAN_STATUS.format(
            code_written=code_written if "code" not in exclude else exclude_prompt,
            task_results=task_results if "task_result" not in exclude else exclude_prompt,
            current_task=self.current_task.instruction,
            current_task_code=self.current_task.code if "code" not in exclude else exclude_prompt,
            current_task_result=self.current_task.result if "task_result" not in exclude else exclude_prompt,
            guidance=guidance,
        )

        return prompt
