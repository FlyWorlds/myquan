export type TodoPriority = 'P0' | 'P1' | 'P2'
export type TodoStatus = 'todo' | 'in_progress' | 'done' | 'deferred'
export type TodoCategory = '策略优化' | '性能加速' | '风控止损' | '前端UI' | '数据接口' | '其他'

export interface ProjectTodo {
  id: string
  title: string
  category: TodoCategory | string
  priority: TodoPriority | string
  status: TodoStatus | string
  content?: string
  target_date?: string
  pinned: boolean
  created_at?: string
  updated_at?: string
}
