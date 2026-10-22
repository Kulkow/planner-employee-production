"""Shared JSON codecs for stored domain snapshots."""

from pydantic import TypeAdapter

from planner.application.planning import PlanningRequest
from planner.domain.jobs import PlanningJob

JOB_CODEC = TypeAdapter(PlanningJob)
REQUEST_CODEC = TypeAdapter(PlanningRequest)
