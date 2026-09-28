"""One writer of story threads at a time (§G #12).

The semantic job (ingest + merge pass) and fusion both read and write threads,
and ran concurrently: the 5-minute jobs start on the same tick, and a "run now"
PROCESS task fuses from the task poller while the scheduled fusion pass is
under way. Measured consequences: the same thread sent to the LLM twice (last
writer wins), fusion snapshotting counts that ingest was changing (the thread
re-fused next cycle), and a merge deleting a thread mid-fusion (the call's
spend wasted, the kept thread paid for again).

The semantic job holds the lock for its whole run; fusion takes it per thread,
so ingest can interleave between threads and never waits behind a whole fusion
pass. A second fusion pass that reaches a thread the first one just finished
finds its members processed and no material increment — it skips on its own.
"""
import threading

THREAD_WRITE_LOCK = threading.RLock()
