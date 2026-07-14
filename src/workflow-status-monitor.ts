import * as core from '@actions/core';
import { getOctokit } from '@actions/github';

export interface StatusUpdate {
  state: string;
  conclusion: string | null;
  started_at: string;
  completed_at: string | null;
  run_url: string;
}

export class WorkflowStatusMonitor {
  private octokit: any;
  private timeoutSeconds: number;

  constructor(
    private owner: string,
    private repo: string,
    private run_id: number,
    private token: string,
    private poll_interval_seconds: number = 30,
    private timeout_minutes: number = 60
  ) {
    this.octokit = getOctokit(token);
    this.timeoutSeconds = timeout_minutes * 60;
  }

  async *start_monitoring(): AsyncGenerator<StatusUpdate, void, unknown> {
    const startTime = Date.now();
    let lastState: string | null = null;

    while (true) {
      const elapsed = (Date.now() - startTime) / 1000;
      if (elapsed > this.timeoutSeconds) {
        throw new Error(`Monitoring timed out after ${this.timeoutSeconds} seconds`);
      }

      try {
        const run = await this.fetchStatusWithRetry();
        const state = run.status;
        const conclusion = run.conclusion;

        if (state !== lastState) {
          core.info(`Workflow ${this.run_id}: ${lastState} → ${state}`);
          lastState = state;
        }

        yield {
          state,
          conclusion,
          started_at: run.run_started_at,
          completed_at: state === 'completed' ? run.updated_at : null,
          run_url: run.html_url
        };

        if (state === 'completed') {
          return;
        }
      } catch (error: any) {
        if (error.status === 401) {
          core.error('Invalid GitHub token provided.');
          throw error;
        }
        throw error;
      }

      await new Promise(resolve => setTimeout(resolve, this.poll_interval_seconds * 1000));
    }
  }

  private async fetchStatusWithRetry(retries = 5, baseDelay = 1000): Promise<any> {
    for (let attempt = 0; attempt < retries; attempt++) {
      try {
        const { data } = await this.octokit.rest.actions.getWorkflowRun({
          owner: this.owner,
          repo: this.repo,
          run_id: this.run_id
        });
        return data;
      } catch (error: any) {
        if ((error.status === 403 || error.status === 429) && attempt < retries - 1) {
          const retryAfter = error.response?.headers?.['retry-after'];
          const delay = retryAfter ? parseInt(retryAfter) * 1000 : baseDelay * Math.pow(2, attempt);
          core.warning(`Rate limited (HTTP ${error.status}). Retrying in ${delay / 1000}s... (Attempt ${attempt + 1}/${retries})`);
          await new Promise(resolve => setTimeout(resolve, delay));
          continue;
        }
        throw error;
      }
    }
  }
}
