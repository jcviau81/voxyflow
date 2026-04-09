/** Card status values — mirrors backend CardStatus enum. */
export const CARD_STATUS = {
  CARD: "card",          // backlog
  TODO: "todo",
  IN_PROGRESS: "in-progress",
  DONE: "done",
  ARCHIVED: "archived",
} as const;

export type CardStatus = (typeof CARD_STATUS)[keyof typeof CARD_STATUS];

/** Worker task status values — mirrors backend WorkerTaskStatus enum. */
export const TASK_STATUS = {
  PENDING: "pending",
  RUNNING: "running",
  DONE: "done",
  FAILED: "failed",
  CANCELLED: "cancelled",
  TIMED_OUT: "timed_out",
} as const;

export type TaskStatus = (typeof TASK_STATUS)[keyof typeof TASK_STATUS];
