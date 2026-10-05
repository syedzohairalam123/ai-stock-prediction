/**
 * Phase 23A — Policy Meeting Card Component
 *
 * Displays upcoming policy meeting information with countdown, meeting type,
 * status, and link to official source.
 */
import React from 'react';
import BaseCard from '../BaseCard';
import BaseBadge from '../BaseBadge';
import { Calendar, Clock, ExternalLink } from 'lucide-react';

interface Countdown {
  days: number;
  hours: number;
  minutes: number;
  seconds: number;
  total_seconds: number;
  is_past: boolean;
}

interface PolicyMeeting {
  id: number;
  central_bank_id: string;
  scheduled_at: string;
  timezone: string;
  status: string;
  meeting_type: string;
  countdown: Countdown;
  current_policy_rate?: number | null;
  previous_decision?: string;
  source_url?: string;
}

interface PolicyMeetingCardProps {
  meeting: PolicyMeeting;
  bankName?: string;
}

export const PolicyMeetingCard: React.FC<PolicyMeetingCardProps> = ({
  meeting,
  bankName,
}) => {
  const getStatusColor = (status: string) => {
    switch (status) {
      case 'UPCOMING':
        return 'bg-blue-100 text-blue-800';
      case 'IN_PROGRESS':
        return 'bg-yellow-100 text-yellow-800';
      case 'COMPLETED':
        return 'bg-green-100 text-green-800';
      case 'CANCELLED':
        return 'bg-red-100 text-red-800';
      default:
        return 'bg-gray-100 text-gray-800';
    }
  };

  const getMeetingTypeColor = (type: string) => {
    switch (type) {
      case 'REGULAR':
        return 'bg-gray-100 text-gray-800';
      case 'EMERGENCY':
        return 'bg-red-100 text-red-800';
      case 'UNSCHEDULED':
        return 'bg-orange-100 text-orange-800';
      default:
        return 'bg-gray-100 text-gray-800';
    }
  };

  const formatCountdown = (countdown: Countdown) => {
    if (countdown.is_past) {
      return 'Passed';
    }
    if (countdown.days > 0) {
      return `${countdown.days}d ${countdown.hours}h`;
    }
    if (countdown.hours > 0) {
      return `${countdown.hours}h ${countdown.minutes}m`;
    }
    return `${countdown.minutes}m`;
  };

  const meetingDate = new Date(meeting.scheduled_at);

  return (
    <BaseCard className="p-4 hover:shadow-md transition-shadow">
      <div className="flex justify-between items-start mb-3">
        <div className="flex-1">
          <h3 className="font-semibold text-gray-900 mb-1">
            {bankName || meeting.central_bank_id}
          </h3>
          <div className="flex items-center gap-2 flex-wrap">
            <BaseBadge variant="outline" size="sm" className={getStatusColor(meeting.status)}>
              {meeting.status}
            </BaseBadge>
            <BaseBadge variant="outline" size="sm" className={getMeetingTypeColor(meeting.meeting_type)}>
              {meeting.meeting_type}
            </BaseBadge>
          </div>
        </div>
        {meeting.source_url && (
          <a
            href={meeting.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
            title="View official source"
          >
            <ExternalLink className="w-4 h-4 text-gray-600" />
          </a>
        )}
      </div>

      {/* Meeting Date */}
      <div className="flex items-center gap-2 mb-3 text-sm text-gray-600">
        <Calendar className="w-4 h-4" />
        <span>
          {meetingDate.toLocaleDateString('en-US', {
            weekday: 'short',
            year: 'numeric',
            month: 'short',
            day: 'numeric',
          })}
        </span>
        <span className="text-gray-400">•</span>
        <span>{meeting.timezone}</span>
      </div>

      {/* Countdown */}
      <div className="flex items-center gap-2 mb-3">
        <Clock className="w-4 h-4 text-gray-600" />
        <span className="text-lg font-semibold text-gray-900">
          {formatCountdown(meeting.countdown)}
        </span>
      </div>

      {/* Current Policy Rate (if available) */}
      {meeting.current_policy_rate != null && (
        <div className="pt-3 border-t border-gray-200">
          <p className="text-xs text-gray-500 uppercase mb-1">Current Policy Rate</p>
          <p className="text-xl font-bold text-gray-900">
            {meeting.current_policy_rate.toFixed(2)}%
          </p>
          {meeting.previous_decision && (
            <p className="text-sm text-gray-600 mt-1">
              Previous: {meeting.previous_decision}
            </p>
          )}
        </div>
      )}
    </BaseCard>
  );
};
