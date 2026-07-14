import { WorkflowStatusMonitor } from './workflow-status-monitor';
import * as core from '@actions/core';

jest.mock('@actions/core');

describe('WorkflowStatusMonitor Unit Tests', () => {
  let monitor: WorkflowStatusMonitor;
  const mockOctokit = {
    rest: {
      actions: {
        getWorkflowRun: jest.fn()
      }
    }
  };

  beforeEach(() => {
    jest.clearAllMocks();
    // @ts-ignore
    require('@actions/github').getOctokit.mockReturnValue(mockOctokit);
    monitor = new WorkflowStatusMonitor('owner', 'repo', 123, 'token', 0.1, 1);
  });

  test('should yield updates until completed', async () => {
    mockOctokit.rest.actions.getWorkflowRun
      .mockResolvedValueOnce({ data: { status: 'queued', conclusion: null, run_started_at: 'start', html_url: 'url' } })
      .mockResolvedValueOnce({ data: { status: 'in_progress', conclusion: null, run_started_at: 'start', html_url: 'url' } })
      .mockResolvedValueOnce({ data: { status: 'completed', conclusion: 'success', run_started_at: 'start', updated_at: 'end', html_url: 'url' } });

    const updates = [];
    for await (const update of monitor.start_monitoring()) {
      updates.push(update);
    }

    expect(updates).toHaveLength(3);
    expect(updates[2].state).toBe('completed');
    expect(updates[2].conclusion).toBe('success');
    expect(core.info).toHaveBeenCalledWith('Workflow 123: in_progress → completed');
  });

  test('should handle rate limits with backoff', async () => {
    const rateLimitError = { status: 403, response: { headers: { 'retry-after': '0.1' } } };
    mockOctokit.rest.actions.getWorkflowRun
      .mockRejectedValueOnce(rateLimitError)
      .mockResolvedValueOnce({ data: { status: 'completed', conclusion: 'success', run_started_at: 'start', updated_at: 'end', html_url: 'url' } });

    const updates = [];
    for await (const update of monitor.start_monitoring()) {
      updates.push(update);
    }

    expect(updates).toHaveLength(1);
    expect(core.warning).toHaveBeenCalledWith(expect.stringContaining('Rate limited'));
  });

  test('should throw error on 401 Unauthorized', async () => {
    mockOctokit.rest.actions.getWorkflowRun.mockRejectedValueOnce({ status: 401 });

    try {
      const generator = monitor.start_monitoring();
      await generator.next();
      fail('Should have thrown');
    } catch (error: any) {
      expect(error.status).toBe(401);
      expect(core.error).toHaveBeenCalledWith('Invalid GitHub token provided.');
    }
  });
});

jest.mock('@actions/github', () => ({
  getOctokit: jest.fn()
}));
