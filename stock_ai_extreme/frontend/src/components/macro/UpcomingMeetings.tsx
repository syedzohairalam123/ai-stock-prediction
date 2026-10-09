/**
 * Phase 23A — Upcoming Meetings Component (spec §8, §9, §18)
 *
 * The meeting calendar section: countdowns computed by the backend from the
 * real tz-aware meeting instants (never a hardcoded countdown), plus the
 * sourced market-implied expectation for a meeting when one exists. A missing
 * calendar is an honest empty state, not a placeholder row.
 */
import React from 'react';
import BaseCard from '../BaseCard';
import { CardSkeleton } from '../LoadingSkeleton';
import { PolicyMeetingCard } from './PolicyMeetingCard';
import type { MarketImpliedExpectation } from './PolicyMeetingCard';

export interface UpcomingMeeting {
  id: number;
  central_bank_id: string;
  scheduled_at: string;
  timezone: string;
  status: string;
  meeting_type: string;
  countdown: {
    days: number;
    hours: number;
    minutes: number;
    seconds: number;
    total_seconds: number;
    is_past: boolean;
  };
  current_policy_rate?: number | null;
  previous_decision?: string;
  source_url?: string;
  /** When the official source itself was captured (spec §8 “Last Updated”). */
  source_timestamp?: string | null;
}

interface UpcomingMeetingsProps {
  meetings: UpcomingMeeting[];
  bankName?: string;
  /** Newest sourced expectation per meeting id, keyed on meeting id. */
  impliedByMeeting?: Map<number, MarketImpliedExpectation>;
  loading?: boolean;
}

export const UpcomingMeetings: React.FC<UpcomingMeetingsProps> = ({
  meetings,
  bankName,
  impliedByMeeting,
  loading = false,
}) => {
  return (
    <section className="mb-6" aria-label="Upcoming policy meetings">
      <h2 className="text-xl font-bold text-gray-900 mb-4">Upcoming Meetings</h2>
      {loading ? (
        <CardSkeleton />
      ) : meetings.length > 0 ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {meetings.map((meeting) => (
            <PolicyMeetingCard
              key={meeting.id}
              meeting={meeting}
              bankName={bankName}
              marketImplied={impliedByMeeting?.get(meeting.id) ?? null}
            />
          ))}
        </div>
      ) : (
        <BaseCard className="p-6">
          <p className="text-center text-gray-500">
            No upcoming meetings scheduled — use “Refresh from official sources”.
          </p>
        </BaseCard>
      )}
    </section>
  );
};

export default UpcomingMeetings;
