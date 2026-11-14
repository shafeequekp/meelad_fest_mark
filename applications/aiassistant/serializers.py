"""Serializers for the AI assistant API.

These convert Django model instances into plain, deliberately whitelisted
dicts. Only the fields the AI assistant needs are exposed — full objects are
never dumped, so we don't accidentally leak sensitive or raw internal fields.
"""
from applications.program.models import Prize


def _dt(dt):
    return dt.isoformat() if dt else None


def team_summary(team):
    return {
        "id": team.id,
        "name": team.name,
        "madrasa": team.madrasa.name if team.madrasa_id else None,
        "colour": team.colour,
    }


def student_summary(student):
    return {
        "id": student.id,
        "full_name": student.full_name,
        "gender": student.gender,
        "team": student.team.name if student.team_id else None,
        "team_id": student.team_id,
        "category": student.category.name if student.category_id else None,
    }


def program_summary(program):
    return {
        "id": program.id,
        "title": program.title,
        "slug": program.slug,
        "is_group": program.is_group,
        "is_general": program.is_general,
        "section": program.section,
        "venue": program.venue.name if program.venue_id else None,
        "venue_id": program.venue_id,
        "scheduled_time": _dt(program.scheduled_time),
        "is_result_published": program.is_result_published,
        "participants_count": program.participants_count(),
        "category": program.program_category(),
    }


def prize_summary(prize):
    def pos(obj):
        return {"name": obj.name, "mark": obj.mark} if obj else None

    return {
        "id": prize.id,
        "program": prize.program.title,
        "program_id": prize.program_id,
        "student": prize.student.full_name if prize.student_id else None,
        "team": prize.team.name if prize.team_id else None,
        "position": pos(prize.position),
        "grade": pos(prize.grade),
        "group_program_position": pos(prize.group_program_position),
        "general_program_position": pos(prize.general_program_position),
        "remarks": prize.remarks,
    }


def venue_summary(venue):
    return {
        "id": venue.id,
        "name": venue.name,
        "description": venue.description,
    }


def leaderboard_row(rank, row):
    team = row["team"]
    return {
        "rank": rank,
        "team": team.name,
        "team_id": team.id,
        "individual_total": round(row["individual_total"], 2),
        "group_total": round(row["group_total"], 2),
        "general_total": round(row["general_total"], 2),
        "grand_total": round(row["grand_total"], 2),
    }