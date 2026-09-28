import axios from 'axios';

const client = axios.create({
  baseURL: 'http://127.0.0.1:8765/api',
  timeout: 15000,
});

/**
 * Start a background run (run-and-trace, trial runs — services/task_runner.py)
 * and wait for it. The endpoint answers {task_id} at once; this polls
 * GET /tasks/{id} until the run finishes. Resolves to `{ data: result }` and
 * rejects like an axios error (`err.response.data.detail`), so call sites keep
 * their existing handling.
 */
export async function runTask<T = any>(url: string, body: any = {}, maxWaitMs = 10 * 60 * 1000): Promise<{ data: T }> {
  const started = await client.post<{ task_id: number }>(url, body);
  const id = started.data.task_id;
  const deadline = Date.now() + maxWaitMs;
  while (Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 1500));
    let t;
    try {
      t = await client.get(`/tasks/${id}`);
    } catch {
      continue; // a missed poll is not a failed run
    }
    const { status, result, error } = t.data;
    if (status === 'COMPLETED') return { data: result as T };
    if (status === 'FAILED' || status === 'SKIPPED') {
      const err: any = new Error(error || 'Task failed');
      err.response = { data: { detail: error || 'Task failed' } };
      throw err;
    }
  }
  const err: any = new Error(`timeout: task #${id} is still running`);
  err.code = 'ECONNABORTED';
  throw err;
}

export default client;
