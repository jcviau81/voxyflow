import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { ActivityEntry, ActivityType, NotificationEntry } from '../types';
import { generateId } from '../lib/utils';

const MAX_NOTIFICATIONS = 100;
const MAX_ACTIVITIES_PER_PROJECT = 50;

export interface NotificationState {
  // Notification center
  notifications: NotificationEntry[];
  notificationUnreadCount: number;

  // Activity feed (per workspace)
  activities: Record<string, ActivityEntry[]>;

  // --- Notifications ---
  addNotification: (entry: Omit<NotificationEntry, 'id' | 'timestamp' | 'read'>) => NotificationEntry;
  markAllNotificationsRead: () => void;
  clearNotifications: () => void;
  getNotifications: () => NotificationEntry[];
  getNotificationUnreadCount: () => number;

  // --- Activity Feed ---
  addActivity: (workspaceId: string, type: ActivityType, message: string) => ActivityEntry;
  getActivities: (workspaceId: string, limit?: number) => ActivityEntry[];
  clearActivities: (workspaceId: string) => void;
}

export const useNotificationStore = create<NotificationState>()(
  persist(
    (set, get) => ({
      notifications: [],
      notificationUnreadCount: 0,
      activities: {},

      // --- Notifications ---

      addNotification(entry) {
        const notification: NotificationEntry = {
          ...entry,
          id: generateId(),
          timestamp: Date.now(),
          read: false,
        };
        set((s) => ({
          notifications: [notification, ...s.notifications].slice(0, MAX_NOTIFICATIONS),
          notificationUnreadCount: s.notificationUnreadCount + 1,
        }));
        return notification;
      },

      markAllNotificationsRead() {
        set((s) => ({
          notifications: s.notifications.map((n) => ({ ...n, read: true })),
          notificationUnreadCount: 0,
        }));
      },

      clearNotifications() {
        set({ notifications: [], notificationUnreadCount: 0 });
      },

      getNotifications() {
        return get().notifications;
      },

      getNotificationUnreadCount() {
        return get().notificationUnreadCount;
      },

      // --- Activity Feed ---

      addActivity(workspaceId, type, message) {
        const entry: ActivityEntry = {
          id: generateId(),
          workspaceId,
          type,
          message,
          timestamp: Date.now(),
        };
        set((s) => {
          const existing = s.activities[workspaceId] || [];
          const updated = [entry, ...existing].slice(0, MAX_ACTIVITIES_PER_PROJECT);
          return {
            activities: { ...s.activities, [workspaceId]: updated },
          };
        });
        return entry;
      },

      getActivities(workspaceId, limit = 10) {
        const all = get().activities[workspaceId] || [];
        return all.slice(0, limit);
      },

      clearActivities(workspaceId) {
        set((s) => {
          const activities = { ...s.activities };
          delete activities[workspaceId];
          return { activities };
        });
      },
    }),
    {
      name: 'voxyflow_notifications',
    },
  ),
);
