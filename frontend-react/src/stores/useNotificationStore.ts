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

  // Activity feed (per project)
  activities: Record<string, ActivityEntry[]>;

  // Unread opportunity badge
  opportunityBadgeCount: number;

  // --- Notifications ---
  addNotification: (entry: Omit<NotificationEntry, 'id' | 'timestamp' | 'read'>) => NotificationEntry;
  markAllNotificationsRead: () => void;
  clearNotifications: () => void;
  getNotifications: () => NotificationEntry[];
  getNotificationUnreadCount: () => number;

  // --- Activity Feed ---
  addActivity: (projectId: string, type: ActivityType, message: string) => ActivityEntry;
  getActivities: (projectId: string, limit?: number) => ActivityEntry[];
  clearActivities: (projectId: string) => void;

  // --- Opportunity Badge ---
  incrementOpportunityBadge: () => void;
  clearOpportunityBadge: () => void;
  getOpportunityBadgeCount: () => number;
}

export const useNotificationStore = create<NotificationState>()(
  persist(
    (set, get) => ({
      notifications: [],
      notificationUnreadCount: 0,
      activities: {},
      opportunityBadgeCount: 0,

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

      addActivity(projectId, type, message) {
        const entry: ActivityEntry = {
          id: generateId(),
          projectId,
          type,
          message,
          timestamp: Date.now(),
        };
        set((s) => {
          const existing = s.activities[projectId] || [];
          const updated = [entry, ...existing].slice(0, MAX_ACTIVITIES_PER_PROJECT);
          return {
            activities: { ...s.activities, [projectId]: updated },
          };
        });
        return entry;
      },

      getActivities(projectId, limit = 10) {
        const all = get().activities[projectId] || [];
        return all.slice(0, limit);
      },

      clearActivities(projectId) {
        set((s) => {
          const activities = { ...s.activities };
          delete activities[projectId];
          return { activities };
        });
      },

      // --- Opportunity Badge ---

      incrementOpportunityBadge() {
        set((s) => ({ opportunityBadgeCount: s.opportunityBadgeCount + 1 }));
      },

      clearOpportunityBadge() {
        set({ opportunityBadgeCount: 0 });
      },

      getOpportunityBadgeCount() {
        return get().opportunityBadgeCount;
      },
    }),
    {
      name: 'voxyflow_notifications',
    },
  ),
);
