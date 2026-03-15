# Qdrant: Local to Cloud

Ira can use **local Qdrant** (Docker), **Qdrant Cloud** only, or **both** (dual-write so local and cloud stay in sync). This doc covers migrating/syncing from local to cloud.

## Quick reference

| Goal | What to do |
|------|------------|
| One-time copy: local → cloud | Set `QDRANT_CLOUD_URL` + `QDRANT_CLOUD_API_KEY`, keep `QDRANT_URL=http://localhost:6333`, then run `ira qdrant sync-to-cloud`. |
| Use cloud only (no local) | Set `QDRANT_URL` to your cloud URL and `QDRANT_API_KEY` to your cloud API key. No Docker Qdrant needed. |
| Keep local + cloud in sync | Set `QDRANT_CLOUD_URL` + `QDRANT_CLOUD_API_KEY`; every upsert and collection create is mirrored to cloud. Run `ira qdrant sync-to-cloud` once to backfill existing data. |

---

## 1. One-time migration (local → cloud)

Use this when you have data in local Qdrant and want to copy it to Qdrant Cloud (e.g. before switching to cloud-only or enabling dual-write).

### Prerequisites

- Local Qdrant running (e.g. `docker compose -f docker-compose.local.yml up -d`) with data in `QDRANT_COLLECTION`.
- A [Qdrant Cloud](https://cloud.qdrant.io/) cluster and API key.

### Steps

1. **Create a cluster** in Qdrant Cloud and note:
   - **Cluster URL** (e.g. `https://xxxxx.region.aws.cloud.qdrant.io:6333`).
   - **API key** from the cluster’s API Keys page.

2. **Configure `.env`** (do not change primary URL yet; sync reads from local, writes to cloud):

   ```bash
   # Keep local as primary for this step
   QDRANT_URL=http://localhost:6333
   QDRANT_COLLECTION=ira_knowledge_v3

   # Cloud destination for sync
   QDRANT_CLOUD_URL=https://YOUR-CLUSTER-ID.region.aws.cloud.qdrant.io:6333
   QDRANT_CLOUD_API_KEY=your_cloud_api_key
   ```

   Leave `QDRANT_API_KEY` unset for local (no auth). If your cloud URL is different, use the exact URL from the Qdrant Cloud console.

3. **Run the one-time sync** from project root:

   ```bash
   poetry run ira qdrant sync-to-cloud
   ```

   Options:

   - `--batch-size 100` — points per batch (default 100).
   - `--max-points N` — cap total points (e.g. for a test run).

   Example with a cap:

   ```bash
   poetry run ira qdrant sync-to-cloud --max-points 500
   ```

4. **Verify** in the Qdrant Cloud UI: open your cluster → Collections → `ira_knowledge_v3` and check point count.

---

## 2. Use cloud only (no local Qdrant)

After syncing (or if you start fresh on cloud):

1. **Point Ira at cloud only** in `.env`:

   ```bash
   QDRANT_URL=https://YOUR-CLUSTER-ID.region.aws.cloud.qdrant.io:6333
   QDRANT_API_KEY=your_cloud_api_key
   QDRANT_COLLECTION=ira_knowledge_v3
   ```

2. **Optional:** Remove or comment out `QDRANT_CLOUD_*`; they are only used for dual-write and sync.

3. You can stop the local Qdrant container; Ira will use cloud for all reads and writes.

---

## 3. Dual-write (local + cloud in sync)

Use this when you want to keep writing to local Qdrant and have the same data in cloud (e.g. for redundancy or a gradual cutover).

1. **One-time backfill** (if local already has data): follow [§1](#1-one-time-migration-local--cloud) so cloud has a copy.

2. **Enable dual-write** in `.env`:

   ```bash
   QDRANT_URL=http://localhost:6333
   QDRANT_COLLECTION=ira_knowledge_v3

   QDRANT_CLOUD_URL=https://YOUR-CLUSTER-ID.region.aws.cloud.qdrant.io:6333
   QDRANT_CLOUD_API_KEY=your_cloud_api_key
   ```

   With both `QDRANT_CLOUD_URL` and `QDRANT_CLOUD_API_KEY` set, `QdrantManager` will:

   - Create the collection on cloud if it doesn’t exist (`ensure_collection`).
   - Mirror every upsert batch to cloud (after writing to local). Cloud write failures are logged and retried once; primary (local) success is still reported.

3. **Ongoing:** All ingestion and any code that uses `QdrantManager.upsert_items` or `ensure_collection` will update both local and cloud.

---

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `QDRANT_URL` | Yes | Primary Qdrant URL (local `http://localhost:6333` or cloud URL). |
| `QDRANT_API_KEY` | For cloud | API key when `QDRANT_URL` is Qdrant Cloud. |
| `QDRANT_COLLECTION` | No | Collection name (default `ira_knowledge_v3`). |
| `QDRANT_CLOUD_URL` | For sync/dual-write | Cloud cluster URL for sync-to-cloud and dual-write. |
| `QDRANT_CLOUD_API_KEY` | For sync/dual-write | Cloud API key. |

---

## Troubleshooting

- **“Qdrant cloud not configured”**  
  Set `QDRANT_CLOUD_URL` and `QDRANT_CLOUD_API_KEY` in `.env` and run the command again.

- **Sync fails with connection / auth errors**  
  Check URL (including `https://` and port `:6333`) and API key in Qdrant Cloud. Ensure the cluster is running and the key has write access.

- **Cloud upsert fails during dual-write or sync (payload/request size)**  
  Primary (local) write still succeeds. Cloud writes use smaller batches (50 points) to reduce payload size. If you still see request-size or 400 errors, run sync with a smaller batch: `ira qdrant sync-to-cloud --batch-size 50` (or 25). Fix cloud URL/key or network and continue; no automatic re-sync of failed batches (you can run `ira qdrant sync-to-cloud` again to re-copy from local if needed).

- **Local Qdrant not running**  
  Start it with `docker compose -f docker-compose.local.yml up -d` from the project root, or switch to cloud-only by setting `QDRANT_URL` and `QDRANT_API_KEY` to your cloud cluster.
