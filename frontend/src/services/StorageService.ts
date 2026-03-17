import { StorageQuery } from '../types';
import { DB_NAME, DB_VERSION, STORAGE_TABLES, AUTO_BACKUP_INTERVAL } from '../utils/constants';

type TableName = (typeof STORAGE_TABLES)[number];

export class StorageService {
  private db: IDBDatabase | null = null;
  private backupTimer: ReturnType<typeof setInterval> | null = null;
  private initPromise: Promise<void> | null = null;

  constructor() {
    this.initPromise = this.init();
    this.startAutoBackup();
  }

  private async init(): Promise<void> {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open(DB_NAME, DB_VERSION);

      request.onupgradeneeded = (event) => {
        const db = (event.target as IDBOpenDBRequest).result;

        for (const table of STORAGE_TABLES) {
          if (!db.objectStoreNames.contains(table)) {
            const store = db.createObjectStore(table, { keyPath: 'key' });
            store.createIndex('timestamp', 'timestamp', { unique: false });
          }
        }
      };

      request.onsuccess = (event) => {
        this.db = (event.target as IDBOpenDBRequest).result;
        console.log('[StorageService] IndexedDB initialized');
        resolve();
      };

      request.onerror = (event) => {
        console.error('[StorageService] IndexedDB error:', (event.target as IDBOpenDBRequest).error);
        reject((event.target as IDBOpenDBRequest).error);
      };
    });
  }

  private async ensureDB(): Promise<IDBDatabase> {
    if (!this.db) {
      await this.initPromise;
    }
    if (!this.db) {
      throw new Error('IndexedDB not available');
    }
    return this.db;
  }

  async set(table: TableName, key: string, value: unknown): Promise<void> {
    const db = await this.ensureDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(table, 'readwrite');
      const store = tx.objectStore(table);
      const record = { key, value, timestamp: Date.now() };

      const request = store.put(record);
      request.onsuccess = () => resolve();
      request.onerror = () => reject(request.error);
    });
  }

  async get(table: TableName, key: string): Promise<unknown | null> {
    const db = await this.ensureDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(table, 'readonly');
      const store = tx.objectStore(table);
      const request = store.get(key);

      request.onsuccess = () => {
        const result = request.result;
        resolve(result ? result.value : null);
      };
      request.onerror = () => reject(request.error);
    });
  }

  async delete(table: TableName, key: string): Promise<void> {
    const db = await this.ensureDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(table, 'readwrite');
      const store = tx.objectStore(table);
      const request = store.delete(key);

      request.onsuccess = () => resolve();
      request.onerror = () => reject(request.error);
    });
  }

  async query(table: TableName, criteria?: StorageQuery): Promise<unknown[]> {
    const db = await this.ensureDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(table, 'readonly');
      const store = tx.objectStore(table);
      const request = store.getAll();

      request.onsuccess = () => {
        let results = request.result.map((r: { value: unknown }) => r.value);

        if (criteria) {
          // Filter by field/value
          if (criteria.field && criteria.value !== undefined) {
            results = results.filter(
              (item: Record<string, unknown>) => item[criteria.field!] === criteria.value
            );
          }

          // Sort
          if (criteria.orderBy) {
            const order = criteria.order || 'asc';
            results.sort((a: Record<string, unknown>, b: Record<string, unknown>) => {
              const aVal = a[criteria.orderBy!];
              const bVal = b[criteria.orderBy!];
              if (aVal < bVal) return order === 'asc' ? -1 : 1;
              if (aVal > bVal) return order === 'asc' ? 1 : -1;
              return 0;
            });
          }

          // Pagination
          if (criteria.offset) {
            results = results.slice(criteria.offset);
          }
          if (criteria.limit) {
            results = results.slice(0, criteria.limit);
          }
        }

        resolve(results);
      };
      request.onerror = () => reject(request.error);
    });
  }

  async clear(table: TableName): Promise<void> {
    const db = await this.ensureDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(table, 'readwrite');
      const store = tx.objectStore(table);
      const request = store.clear();

      request.onsuccess = () => resolve();
      request.onerror = () => reject(request.error);
    });
  }

  async count(table: TableName): Promise<number> {
    const db = await this.ensureDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(table, 'readonly');
      const store = tx.objectStore(table);
      const request = store.count();

      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }

  async exportAll(): Promise<Record<string, unknown[]>> {
    const data: Record<string, unknown[]> = {};
    for (const table of STORAGE_TABLES) {
      data[table] = await this.query(table);
    }
    return data;
  }

  async importAll(data: Record<string, unknown[]>): Promise<void> {
    for (const [table, items] of Object.entries(data)) {
      if (STORAGE_TABLES.includes(table as TableName)) {
        await this.clear(table as TableName);
        for (const item of items) {
          const record = item as Record<string, unknown>;
          if (record.id) {
            await this.set(table as TableName, record.id as string, item);
          }
        }
      }
    }
  }

  // --- Auto-backup ---

  private startAutoBackup(): void {
    this.backupTimer = setInterval(async () => {
      try {
        const data = await this.exportAll();
        localStorage.setItem('voxyflow_backup', JSON.stringify({
          timestamp: Date.now(),
          data,
        }));
      } catch (e) {
        console.warn('[StorageService] Auto-backup failed:', e);
      }
    }, AUTO_BACKUP_INTERVAL);
  }

  destroy(): void {
    if (this.backupTimer) {
      clearInterval(this.backupTimer);
      this.backupTimer = null;
    }
    if (this.db) {
      this.db.close();
      this.db = null;
    }
  }
}

export const storageService = new StorageService();
