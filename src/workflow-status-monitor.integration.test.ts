import { WorkflowStatusMonitor } from './workflow-status-monitor';

describe('WorkflowStatusMonitor Integration Tests', () => {
  const owner = 'JsonLord';
  const repo = 'event-scraper-github-actions';
  const run_id = 456;
  const token = 'ghp_fakeTokenForTesting';

  let mockActions: any;
  let mockOctokit: any;

  beforeEach(() => {
    mockActions = {
      getWorkflowRun: jest.fn()
    };
    mockOctokit = {
      rest: {
        actions: mockActions
      }
    };
    // @ts-ignore
    require('@actions/github').getOctokit.mockReturnValue(mockOctokit);
  });

  test('full lifecycle: queued -> in_progress -> completed', async () => {
    mockActions.getWorkflowRun
      .mockResolvedValueOnce({ data: { status: 'queued', conclusion: null, run_started_at: '2023-10-27T10:00:00Z', html_url: 'url' } })
      .mockResolvedValueOnce({ data: { status: 'in_progress', conclusion: null, run_started_at: '2023-10-27T10:00:00Z', html_url: 'url' } })
      .mockResolvedValueOnce({ data: { status: 'completed', conclusion: 'success', run_started_at: '2023-10-27T10:00:00Z', updated_at: '2023-10-27T10:05:00Z', html_url: 'url' } });

    const monitor = new WorkflowStatusMonitor(owner, repo, run_id, token, 0.1, 1);
    const updates = [];
    for await (const update of monitor.start_monitoring()) {
      updates.push(update);
    }

    expect(updates).toHaveLength(3);
    expect(updates[0].state).toBe('queued');
    expect(updates[1].state).toBe('in_progress');
    expect(updates[2].state).toBe('completed');
  });

  test('handles 403 rate limit with retry', async () => {
    mockActions.getWorkflowRun
      .mockRejectedValueOnce({ status: 403, response: { headers: { 'retry-after': '0.1' } } })
      .mockResolvedValueOnce({ data: { status: 'completed', conclusion: 'success', run_started_at: '2023-10-27T10:00:00Z', updated_at: '2023-10-27T10:05:00Z', html_url: 'url' } });

    const monitor = new WorkflowStatusMonitor(owner, repo, run_id, token, 0.1, 1);
    const updates = [];
    for await (const update of monitor.start_monitoring()) {
      updates.push(update);
    }

    expect(updates).toHaveLength(1);
    expect(updates[0].state).toBe('completed');
  });
});

jest.mock('@actions/github', () => ({
  getOctokit: jest.fn()
}));
