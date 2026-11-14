import asyncio


async def main(job):
    polars, ibis = await asyncio.gather(job.run_node("asker", {"who": "polars"}), job.run_node("asker", {"who": "ibis"}))
    return {"returned": [polars, ibis]}
