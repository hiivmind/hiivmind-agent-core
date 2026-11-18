import asyncio


async def main(job):
    first, second = await asyncio.gather(
        job.run_node("refresh", {"sources": "polars"}),
        job.run_node("refresh", {"sources": "ibis"}),
    )
    return {"returned": [first, second]}
