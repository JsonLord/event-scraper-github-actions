import { WorkflowStatusMonitor } from '../src/workflow-status-monitor';

async function main() {
  const owner = process.env.GITHUB_OWNER || 'JsonLord';
  const repo = process.env.GITHUB_REPO || 'event-scraper-github-actions';
  const run_id = parseInt(process.env.GITHUB_RUN_ID || '123456789');
  const token = process.env.GITHUB_TOKEN || 'your-token-here';

  console.log(`--- Monitoring Workflow Run ${run_id} in ${owner}/${repo} ---`);

  const monitor = new WorkflowStatusMonitor(owner, repo, run_id, token, 10, 60);

  try {
    for await (const update of monitor.start_monitoring()) {
      console.log(`Update: State=${update.state}, Conclusion=${update.conclusion}`);
      if (update.state === 'completed') {
        console.log(`Workflow finished with conclusion: ${update.conclusion}`);
        console.log(`Run URL: ${update.run_url}`);
      }
    }
  } catch (error: any) {
    console.error(`An error occurred: ${error.message}`);
  }
}

main().catch(console.error);
