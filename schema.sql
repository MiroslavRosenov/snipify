CREATE TABLE IF NOT EXISTS public.urls (
	id SERIAL NOT NULL,
    origin TEXT NOT NULL UNIQUE,
    alias TEXT NOT NULL UNIQUE,
    created_by BIGINT NOT NULL,

    PRIMARY KEY (id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_origin_unique
    ON public.urls(origin);

CREATE UNIQUE INDEX IF NOT EXISTS idx_alias_unique
    ON public.urls(alias);

CREATE INDEX IF NOT EXISTS idx_created_by
    ON public.urls(created_by);

--

CREATE TABLE IF NOT EXISTS public.users (
	id SERIAL NOT NULL,
    email TEXT NOT NULL UNIQUE,
    hashed_password TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT False,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    PRIMARY KEY (id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_email_unique
    ON public.users(LOWER(email));

--

CREATE TABLE IF NOT EXISTS public.refresh_tokens (
    id SERIAL NOT NULL,
    owner_id BIGINT NOT NULL,
    refresh_token TEXT NOT NULL UNIQUE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,

    FOREIGN KEY (owner_id)
        REFERENCES public.users(id)
            ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_owner_id
    ON public.refresh_tokens(owner_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_refresh_token
    ON public.refresh_tokens(refresh_token);

--

CREATE TYPE public.one_time_token_purpose AS ENUM (
    'password_reset',
    'account_activation'
);

CREATE TABLE IF NOT EXISTS public.one_time_tokens (
    id SERIAL NOT NULL,
    owner_id BIGINT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    purpose public.one_time_token_purpose NOT NULL,
    used BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,

    PRIMARY KEY (id),
    FOREIGN KEY (owner_id)
        REFERENCES public.users(id)
            ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_one_time_token_hash
    ON public.one_time_tokens(token_hash);

CREATE INDEX IF NOT EXISTS idx_one_time_token_owner_purpose
    ON public.one_time_tokens(owner_id, purpose);


-- Migrations: fix DEFAULT on already-existing tables
ALTER TABLE public.users
    ALTER COLUMN created_at SET DEFAULT NOW();

ALTER TABLE public.refresh_tokens
    ALTER COLUMN created_at SET DEFAULT NOW();
