# MyUniversity – MBTI-Based Recommendation Database Project

## Overview
MyUniversity is a database-driven web platform that provides
personalized recommendations for university lectures, clubs,
and activities based on individual student profiles.

The system uses MBTI personality type, major, year level,
and preferred time to generate dynamic, user-specific
recommendations using SQL-based rating and sorting logic.

## Key Features
- MBTI-based personalized recommendation
- Role-based system (Student / Club Leader / Staff)
- SQL-centered recommendation logic
- Real-time recommendation updates on profile change
- Capacity limits enforced at database level

## Tech Stack
- Backend: Python (Flask)
- Frontend: HTML, CSS, Jinja2
- Database: PostgreSQL

## Database Design
- Fully normalized schema (3NF)
- Many-to-many relationships via application tables
- Foreign Key and CHECK constraints
- Recommendation scores stored in rating tables

## Recommendation Logic
Recommendations are generated using LEFT JOIN and COALESCE
to combine user MBTI with rating tables and sorted using
ORDER BY rating DESC.

## Project Type
University Database Programming Final Project
