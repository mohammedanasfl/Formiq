# Formiq
Adaptive AI fitness coach for personalized workouts, nutrition, recovery, and progress.

## Status

The backend foundation and the user/profile API are in place (phases 1 to 2.5): a FastAPI
application backed by PostgreSQL that creates users and stores their onboarding profile.
AI coaching, workouts, nutrition, recovery, progress tracking, authentication, and the mobile app
are planned for later phases.

## Repository structure

```
formiq/
├── backend/              # Python backend (FastAPI, PostgreSQL); see backend/README.md
├── frontend/             # React Native app (later phase)
├── docs/                 # Project documentation
├── docker/postgres/      # PostgreSQL initialization script (creates the test database)
├── docker-compose.yml    # Local PostgreSQL for development and tests
├── .gitignore
└── README.md
```

## Getting started

See [backend/README.md](backend/README.md) for setting up the backend, running the API,
database migrations, and tests.

## Development approach

Formiq is being developed phase-by-phase using AI-assisted coding, with each phase reviewed
against a Definition of Done, rather than through uncontrolled code generation.
