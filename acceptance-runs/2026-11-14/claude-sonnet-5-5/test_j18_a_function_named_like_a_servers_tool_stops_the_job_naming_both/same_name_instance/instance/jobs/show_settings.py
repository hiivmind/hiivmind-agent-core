async def main(job):
    s = job.settings
    return {"name": s.CORPUS_NAME, "path": s.CORPUS_PATH, "repo": s.CORPUS_REPO, "prefix": s.BRANCH_PREFIX}
