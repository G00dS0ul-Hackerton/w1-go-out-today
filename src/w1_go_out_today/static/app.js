document.addEventListener('DOMContentLoaded', () => {
    // DOM Elements
    const skyContainer = document.getElementById('skyContainer');
    const celestialBody = document.getElementById('celestialBody');
    const cloudLayer = document.getElementById('cloudLayer');
    const rainContainer = document.getElementById('rainContainer');
    const greeting = document.getElementById('greeting');
    const honestyBanner = document.getElementById('honestyBanner');
    const eveningNote = document.getElementById('eveningNote');
    const weatherCloud = document.getElementById('weatherCloud');
    const wcTemp = document.getElementById('wcTemp');
    const wcRain = document.getElementById('wcRain');
    const playBtn = document.getElementById('playBtn');
    const playIcon = document.getElementById('playIcon');
    const stopBtn = document.getElementById('stopBtn');
    const statusDot = document.getElementById('statusDot');
    const waveformCanvas = document.getElementById('waveformCanvas');
    const chips = document.querySelectorAll('.chip');
    const progressChips = document.getElementById('progressChips');
    const activeStepContainer = document.getElementById('activeStepContainer');
    const stepCard = document.getElementById('stepCard');
    const stepIcon = document.getElementById('stepIcon');
    const stepLabel = document.getElementById('stepLabel');
    const timeline = document.getElementById('timeline');
    const timelineTooltip = document.getElementById('timelineTooltip');
    const brief = document.getElementById('brief');
    const captionsContainer = document.getElementById('captionsContainer');
    const briefNote = document.getElementById('briefNote');
    const characterStage = document.getElementById('characterStage');
    const grassGround = document.getElementById('grassGround');
    const outside = document.getElementById('outside');
    const outsideBtn = document.getElementById('outsideBtn');
    const outsideForm = document.getElementById('outsideForm');
    const outsideNote = document.getElementById('outsideNote');
    const outsideSubmit = document.getElementById('outsideSubmit');
    const outsideConfirm = document.getElementById('outsideConfirm');

    // State
    let eventSource = null;
    let briefData = null;
    let autoPlayPending = false;
    let currentActivity = localStorage.getItem('activity') || 'a walk';
    let currentAbortController = null;
    let currentRequestId = null;
    let isBuildingOrPlaying = false;
    let currentAudio = null;
    let audioCtx = null;
    let analyser = null;
    let sourceNode = null;
    let waveformAnimId = null;
    let cachedForecast = null;
    let currentRainProb = 0;
    let captionController = null;
    let smoothedLoudness = 0;
    let pauseEaseProgress = 1.0;

    // Step definitions
    const STEP_INFO = {
        reading_sky: { icon: '☁️', label: 'Reading the sky…' },
        tabpfn: { icon: '🧠', label: 'TabPFN is forecasting 12 hours…' },
        plan: { icon: '✍️', label: 'Writing your plan…' },
        voice: { icon: '🎙️', label: 'Recording your brief…' }
    };

    // -----------------------------------------------------------------------
    // Time & Sky Environment
    // -----------------------------------------------------------------------
    function updateEnvironment() {
        const now = new Date();
        const hour = now.getHours();

        // Sky phase class
        skyContainer.classList.remove('sky-dawn', 'sky-day', 'sky-sunset', 'sky-night');
        let phase = 'day';
        if (hour >= 5 && hour < 8) {
            skyContainer.classList.add('sky-dawn');
            phase = 'dawn';
            greeting.textContent = 'Good morning, Lagos';
        } else if (hour >= 8 && hour < 17) {
            skyContainer.classList.add('sky-day');
            phase = 'day';
            greeting.textContent = hour < 12 ? 'Good morning, Lagos' : 'Good afternoon, Lagos';
        } else if (hour >= 17 && hour < 19) {
            skyContainer.classList.add('sky-sunset');
            phase = 'sunset';
            greeting.textContent = 'Good evening, Lagos';
        } else {
            skyContainer.classList.add('sky-night');
            phase = 'night';
            greeting.textContent = (hour >= 19 && hour < 22) ? 'Good evening, Lagos' : 'Good night, Lagos';
        }

        // Evening / morning pill
        if (hour >= 18) {
            eveningNote.textContent = "Tomorrow's brief builds at 05:45";
            eveningNote.removeAttribute('hidden');
        } else if (hour >= 5 && hour < 12) {
            eveningNote.textContent = "Today's brief \u00b7 forecast from 06:00";
            eveningNote.removeAttribute('hidden');
        } else {
            eveningNote.setAttribute('hidden', '');
        }

        // Sun / Moon arc position
        const isDay = hour >= 6 && hour < 18;
        const progress = isDay ? (hour - 6 + now.getMinutes() / 60) / 12 : (hour >= 18 ? (hour - 18 + now.getMinutes() / 60) / 12 : (hour + 6 + now.getMinutes() / 60) / 12);
        const xPct = 12 + progress * 76;
        const yPct = 70 - Math.sin(progress * Math.PI) * 55;

        celestialBody.style.transform = `translate(${xPct}vw, ${yPct}vh)`;
        celestialBody.innerHTML = isDay ? getSunSVG() : getMoonSVG();

        return phase;
    }

    function getSunSVG() {
        return `<svg viewBox="0 0 60 60" class="celestial-svg"><circle cx="30" cy="30" r="18" fill="#facc15"/><circle cx="30" cy="30" r="24" fill="none" stroke="#fef08a" stroke-width="2" stroke-dasharray="4 4" opacity="0.6"/></svg>`;
    }

    function getMoonSVG() {
        return `<svg viewBox="0 0 60 60" class="celestial-svg"><path d="M38,15 A18,18 0 1,1 25,48 A22,22 0 1,0 38,15 Z" fill="#f1f5f9"/></svg>`;
    }

    const currentSkyPhase = updateEnvironment();

    // -----------------------------------------------------------------------
    // Animated Characters (Parts A & B)
    // -----------------------------------------------------------------------
    // Animated Characters (~2x size with night outlines & articulated walker)
    // -----------------------------------------------------------------------
    function renderCharacter(activity, rainProb) {
        characterStage.innerHTML = '';
        const actor = document.createElement('div');
        actor.className = 'activity-actor';
        actor.id = 'activeActor';

        const showUmbrella = rainProb >= 40;
        const umbrellaSVG = showUmbrella ? `
            <g class="umbrella-addon">
                <path d="M26,16 A22,22 0 0,1 74,16 Z" fill="#ef4444"/>
                <line x1="50" y1="16" x2="50" y2="52" stroke="#334155" stroke-width="3"/>
                <path d="M50,52 A5,5 0 0,1 42,52" fill="none" stroke="#334155" stroke-width="3"/>
            </g>
        ` : '';

        const act = activity.toLowerCase();
        if (act.includes('walk')) {
            actor.classList.add('actor-walk');
            actor.innerHTML = `
                <svg viewBox="0 0 100 130" width="100" height="130">
                    ${umbrellaSVG}
                    <!-- Head -->
                    <circle cx="50" cy="22" r="11" fill="#1e293b"/>
                    <!-- Torso with shirt -->
                    <path d="M42,34 C42,32 58,32 58,34 L56,70 C56,72 44,72 44,70 Z" fill="#3b82f6"/>
                    <!-- Left arm -->
                    <path class="arm arm-left" d="M44,38 L30,58 L20,54" stroke="#1e293b" stroke-width="4.5" stroke-linecap="round" fill="none"/>
                    <!-- Right arm -->
                    <path class="arm arm-right" d="M56,38 L70,58 L80,54" stroke="#1e293b" stroke-width="4.5" stroke-linecap="round" fill="none"/>
                    <!-- Left leg with shoe -->
                    <path class="leg leg-left" d="M46,70 L40,96 L32,122 L22,122" stroke="#1e293b" stroke-width="5" stroke-linecap="round" fill="none"/>
                    <!-- Right leg with shoe -->
                    <path class="leg leg-right" d="M54,70 L60,96 L68,122 L78,122" stroke="#1e293b" stroke-width="5" stroke-linecap="round" fill="none"/>
                </svg>
            `;
        } else if (act.includes('run')) {
            actor.classList.add('actor-run');
            actor.innerHTML = `
                <svg viewBox="0 0 120 130" width="120" height="130">
                    <circle cx="50" cy="24" r="11" fill="#1e293b"/>
                    <path d="M42,36 L58,36 L54,72 L42,72 Z" fill="#ef4444"/>
                    <path class="leg leg-left" d="M44,72 L30,98 L14,122" stroke="#1e293b" stroke-width="5" stroke-linecap="round" fill="none"/>
                    <path class="leg leg-right" d="M54,72 L72,98 L92,122" stroke="#1e293b" stroke-width="5" stroke-linecap="round" fill="none"/>
                    <path d="M44,40 L26,56 L16,50" stroke="#1e293b" stroke-width="4" stroke-linecap="round" fill="none"/>
                    <path d="M56,40 L76,56 L86,52" stroke="#1e293b" stroke-width="4" stroke-linecap="round" fill="none"/>
                </svg>
            `;
        } else if (act.includes('football')) {
            actor.classList.add('actor-football');
            actor.innerHTML = `
                <svg viewBox="0 0 160 130" width="160" height="130">
                    ${umbrellaSVG}
                    <circle cx="50" cy="26" r="10" fill="#1e293b"/>
                    <path d="M43,38 L57,38 L55,74 L43,74 Z" fill="#10b981"/>
                    <line x1="45" y1="74" x2="34" y2="122" stroke="#1e293b" stroke-width="5" stroke-linecap="round"/>
                    <line class="kicking-leg" x1="53" y1="74" x2="78" y2="105" stroke="#1e293b" stroke-width="5" stroke-linecap="round"/>
                    <circle class="soccer-ball" cx="100" cy="115" r="10" fill="#f8fafc" stroke="#1e293b" stroke-width="2.5"/>
                </svg>
            `;
        } else if (act.includes('market')) {
            actor.classList.add('actor-market');
            actor.innerHTML = `
                <svg viewBox="0 0 120 130" width="120" height="130">
                    ${umbrellaSVG}
                    <circle cx="55" cy="24" r="11" fill="#1e293b"/>
                    <path d="M46,36 L64,36 L62,72 L46,72 Z" fill="#8b5cf6"/>
                    <line class="leg leg-left" x1="48" y1="72" x2="38" y2="120" stroke="#1e293b" stroke-width="5" stroke-linecap="round"/>
                    <line class="leg leg-right" x1="60" y1="72" x2="72" y2="120" stroke="#1e293b" stroke-width="5" stroke-linecap="round"/>
                    <g class="market-bag bag-left">
                        <rect x="20" y="60" width="20" height="26" rx="3" fill="#e11d48"/>
                    </g>
                    <g class="market-bag bag-right">
                        <rect x="72" y="60" width="20" height="26" rx="3" fill="#0284c7"/>
                    </g>
                </svg>
            `;
        } else if (act.includes('dry clothes')) {
            actor.classList.add('actor-clothes');
            actor.innerHTML = `
                <svg viewBox="0 0 240 130" width="240" height="130">
                    <line x1="15" y1="20" x2="15" y2="125" stroke="#78350f" stroke-width="5" stroke-linecap="round"/>
                    <line x1="225" y1="20" x2="225" y2="125" stroke="#78350f" stroke-width="5" stroke-linecap="round"/>
                    <path d="M15,36 Q120,52 225,36" fill="none" stroke="#94a3b8" stroke-width="2.5"/>
                    <g class="hanging-shirt shirt-1">
                        <path d="M45,44 L66,44 L70,56 L62,58 L60,82 L48,82 L46,58 L38,56 Z" fill="#3b82f6"/>
                    </g>
                    <g class="hanging-shirt shirt-2">
                        <path d="M105,48 L126,48 L130,60 L122,62 L120,86 L108,86 L106,62 L98,60 Z" fill="#ec4899"/>
                    </g>
                    <g class="hanging-shirt shirt-3">
                        <path d="M165,46 L188,46 L192,88 L180,88 L177,66 L174,88 L162,88 Z" fill="#64748b"/>
                    </g>
                </svg>
            `;
        } else if (act.includes('commute')) {
            actor.classList.add('actor-danfo');
            actor.innerHTML = `
                <svg viewBox="0 0 180 100" width="180" height="100">
                    <rect x="15" y="25" width="150" height="52" rx="7" fill="#facc15"/>
                    <rect x="15" y="50" width="150" height="6" fill="#0f172a"/>
                    <rect x="15" y="62" width="150" height="6" fill="#0f172a"/>
                    <rect x="25" y="32" width="28" height="15" rx="3" fill="#38bdf8"/>
                    <rect x="62" y="32" width="36" height="15" rx="3" fill="#38bdf8"/>
                    <rect x="108" y="32" width="44" height="15" rx="3" fill="#38bdf8"/>
                    <circle class="danfo-wheel" cx="48" cy="78" r="12" fill="#1e293b"/>
                    <circle cx="48" cy="78" r="5" fill="#94a3b8"/>
                    <circle class="danfo-wheel" cx="132" cy="78" r="12" fill="#1e293b"/>
                    <circle cx="132" cy="78" r="5" fill="#94a3b8"/>
                </svg>
            `;
        } else if (act.includes('picnic')) {
            actor.classList.add('actor-picnic');
            actor.innerHTML = `
                <svg viewBox="0 0 180 100" width="180" height="100">
                    ${umbrellaSVG}
                    <polygon points="15,92 165,92 145,70 35,70" fill="#f43f5e"/>
                    <rect x="50" y="64" width="30" height="22" rx="3" fill="#b45309"/>
                    <circle cx="115" cy="46" r="10" fill="#1e293b"/>
                    <path d="M115,56 L115,78 L96,82" fill="none" stroke="#1e293b" stroke-width="6" stroke-linecap="round"/>
                </svg>
            `;
        } else if (act.includes('hangout')) {
            actor.classList.add('actor-hangout');
            actor.innerHTML = `
                <svg viewBox="0 0 180 110" width="180" height="110">
                    ${umbrellaSVG}
                    <circle cx="60" cy="38" r="10" fill="#1e293b"/>
                    <line x1="60" y1="48" x2="60" y2="90" stroke="#1e293b" stroke-width="6" stroke-linecap="round"/>
                    <circle cx="95" cy="40" r="10" fill="#1e293b"/>
                    <line x1="95" y1="50" x2="95" y2="90" stroke="#1e293b" stroke-width="6" stroke-linecap="round"/>
                    <g class="balloon-group">
                        <path d="M120,20 A12,15 0 1,1 119.9,20 Z" fill="#8b5cf6"/>
                        <path d="M120,35 Q115,55 108,70" fill="none" stroke="#cbd5e1" stroke-width="2"/>
                        <path d="M136,24 A10,13 0 1,1 135.9,24 Z" fill="#f43f5e"/>
                    </g>
                    <text class="music-note" x="72" y="25" font-size="18" fill="#f59e0b">♪</text>
                </svg>
            `;
        }
        characterStage.appendChild(actor);
    }

    renderCharacter(currentActivity, currentRainProb);

    // -----------------------------------------------------------------------
    // Chips & Activity Management with Locking & Spinners (Bugs 1 & 3)
    // -----------------------------------------------------------------------
    function lockChips(activeActivity) {
        isBuildingOrPlaying = true;
        chips.forEach(chip => {
            const sp = chip.querySelector('.chip-spinner');
            if (sp) sp.remove();

            if (chip.dataset.activity === activeActivity) {
                chip.classList.add('chip--active');
                chip.disabled = false;
                chip.removeAttribute('aria-disabled');
                chip.classList.remove('chip--disabled');
                const spinner = document.createElement('span');
                spinner.className = 'chip-spinner';
                spinner.setAttribute('aria-hidden', 'true');
                chip.appendChild(spinner);
            } else {
                chip.classList.remove('chip--active');
                chip.disabled = true;
                chip.setAttribute('aria-disabled', 'true');
                chip.classList.add('chip--disabled');
            }
        });
        if (stopBtn) stopBtn.removeAttribute('hidden');
    }

    function unlockChips() {
        isBuildingOrPlaying = false;
        chips.forEach(chip => {
            const sp = chip.querySelector('.chip-spinner');
            if (sp) sp.remove();
            chip.disabled = false;
            chip.removeAttribute('aria-disabled');
            chip.classList.remove('chip--disabled');
            if (chip.dataset.activity === currentActivity) {
                chip.classList.add('chip--active');
            } else {
                chip.classList.remove('chip--active');
            }
        });
        if (stopBtn) stopBtn.setAttribute('hidden', '');
    }

    function updateChips(activeActivity) {
        if (!isBuildingOrPlaying) {
            chips.forEach(chip => {
                if (chip.dataset.activity === activeActivity) {
                    chip.classList.add('chip--active');
                } else {
                    chip.classList.remove('chip--active');
                }
            });
        }
    }

    updateChips(currentActivity);

    chips.forEach(chip => {
        chip.addEventListener('click', (e) => {
            if (isBuildingOrPlaying) return;
            const newAct = chip.dataset.activity || e.target.dataset.activity;
            if (!newAct || newAct === currentActivity) return;

            // Stop any playing audio cleanly to prevent double audio
            stopAudio(true);

            currentActivity = newAct;
            localStorage.setItem('activity', currentActivity);
            updateChips(currentActivity);
            renderCharacter(currentActivity, currentRainProb);
            startBrief(currentActivity);

    // Warm Ollama model on page open
    fetch('/warm').catch(() => {});
        });
    });

    if (stopBtn) {
        stopBtn.addEventListener('click', () => {
            stopAudio(true);
            statusDot.className = 'play-btn__dot dot--ready';
        });
    }

    // -----------------------------------------------------------------------
    // Single-Step Progression UI
    // -----------------------------------------------------------------------
    function showActiveStep(stepKey) {
        activeStepContainer.removeAttribute('hidden');
        const info = STEP_INFO[stepKey] || { icon: '⏳', label: 'Processing…' };
        stepIcon.textContent = info.icon;
        stepLabel.textContent = info.label;
    }

    function markStepDone(stepKey) {
        const chip = document.getElementById(`chip-${stepKey}`);
        if (chip) chip.removeAttribute('hidden');
    }

    function resetStepsUI() {
        progressChips.removeAttribute('hidden');
        document.querySelectorAll('.chip-check').forEach(c => c.setAttribute('hidden', ''));
    }

    // -----------------------------------------------------------------------
    // Pipeline & SSE Management (Bugs 1, 3, 5)
    // -----------------------------------------------------------------------
    function startBrief(activity) {
        if (currentAbortController) {
            currentAbortController.abort();
        }
        currentAbortController = new AbortController();
        currentRequestId = 'req_' + Date.now() + '_' + Math.random().toString(36).substring(2, 8);

        if (eventSource) {
            eventSource.close();
        }

        briefData = null;
        autoPlayPending = false;
        statusDot.className = 'play-btn__dot dot--building';
        playIcon.textContent = '▶';

        lockChips(activity);

        resetStepsUI();
        timeline.setAttribute('hidden', '');
        brief.setAttribute('hidden', '');
        outside.setAttribute('hidden', '');
        outsideBtn.removeAttribute('hidden');
        outsideForm.setAttribute('hidden', '');
        if (outsideConfirm) outsideConfirm.setAttribute('hidden', '');
        grassGround.classList.remove('grass--tall');

        const thisRequestId = currentRequestId;
        const thisActivity = activity;

        fetch('/brief', {
            method: 'POST',
            signal: currentAbortController.signal,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ activity: activity, request_id: thisRequestId })
        }).catch(err => {
            if (err.name !== 'AbortError') {
                console.warn('Brief request error:', err);
                unlockChips();
            }
        });

        eventSource = new EventSource('/events?activity=' + encodeURIComponent(activity));

        eventSource.addEventListener('progress', (e) => {
            const data = JSON.parse(e.data);
            if (data.activity && data.activity !== currentActivity) return;
            if (data.request_id && data.request_id !== currentRequestId) return;

            if (data.status === 'running') {
                showActiveStep(data.step);
            } else if (data.status === 'done') {
                markStepDone(data.step);
            }
        });

        eventSource.addEventListener('forecast_ready', (e) => {
            const data = JSON.parse(e.data);
            if (data.activity && data.activity !== currentActivity) return;
            if (data.request_id && data.request_id !== currentRequestId) return;

            cachedForecast = data.forecast;
            renderTimeline(data.forecast, data.facts);

            // Bug 5 fix: if forecast was cached, instantly show "Forecast ready ✓"
            if (data.forecast_cached) {
                markStepDone('reading_sky');
                markStepDone('tabpfn');
                const tabpfnChip = document.getElementById('chip-tabpfn');
                if (tabpfnChip) {
                    tabpfnChip.textContent = '✓ Forecast ready';
                    tabpfnChip.removeAttribute('hidden');
                }
            }

            // Update Weather Cloud & Honesty banner
            if (data.forecast && data.forecast.length > 0) {
                const first = data.forecast[0];
                wcTemp.textContent = first.temp_pred;
                wcRain.textContent = `${first.rain_prob} rain`;
                weatherCloud.removeAttribute('hidden');

                currentRainProb = parseInt(first.rain_prob, 10) || 0;
                renderCharacter(currentActivity, currentRainProb);

                // Rain drops animation
                if (currentRainProb >= 60) {
                    rainContainer.removeAttribute('hidden');
                    cloudLayer.style.color = '#475569';
                } else if (currentRainProb >= 30) {
                    rainContainer.setAttribute('hidden', '');
                    cloudLayer.style.color = '#94a3b8';
                } else {
                    rainContainer.setAttribute('hidden', '');
                    cloudLayer.style.color = 'rgba(255, 255, 255, 0.85)';
                }
            }

            // Honesty metadata
            const dateStr = new Date().toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' });
            const dataUpTo = data.data_up_to || 'recent';
            honestyBanner.textContent = `Forecast from 06:00 ${dateStr} · data up to ${dataUpTo}`;
        });

        eventSource.addEventListener('brief_ready', (e) => {
            const data = JSON.parse(e.data);
            if (data.activity && data.activity !== currentActivity) return;
            if (data.request_id && data.request_id !== currentRequestId) return;

            briefData = data;
            activeStepContainer.setAttribute('hidden', '');
            statusDot.className = 'play-btn__dot dot--ready';

            markStepDone('reading_sky');
            markStepDone('tabpfn');
            markStepDone('plan');
            markStepDone('voice');

            if (autoPlayPending) {
                playBrief();
            } else {
                unlockChips();
            }
            if (eventSource) eventSource.close();
        });

        eventSource.addEventListener('error', (e) => {
            console.warn('SSE event error:', e);
            unlockChips();
        });
    }

    startBrief(currentActivity);

    // Warm Ollama model on page open
    fetch('/warm').catch(() => {});


    // -----------------------------------------------------------------------
    // Timeline Tooltips & Now Marker (Part C)
    // -----------------------------------------------------------------------
    function renderTimeline(forecastData, facts) {
        if (!forecastData || forecastData.length === 0) return;
        timeline.innerHTML = '';
        timeline.removeAttribute('hidden');

        const nowHour = new Date().getHours();
        const bestStart = facts?.best_window ? parseInt(facts.best_window.start.split(':')[0], 10) : -1;
        const bestEnd = facts?.best_window ? parseInt(facts.best_window.end.split(':')[0], 10) : -1;
        const avoidStart = facts?.avoid_window ? parseInt(facts.avoid_window.start.split(':')[0], 10) : -1;
        const avoidEnd = facts?.avoid_window ? parseInt(facts.avoid_window.end.split(':')[0], 10) : -1;

        forecastData.forEach((row, i) => {
            const bar = document.createElement('div');
            bar.className = 'timeline__bar';

            const rainVal = parseInt(row.rain_prob, 10) || 0;
            const hourVal = parseInt(row.time.split(':')[0], 10);

            // Bar color
            if (bestStart !== -1 && hourVal >= bestStart && hourVal <= bestEnd) {
                bar.classList.add('timeline__bar--best');
            } else if (avoidStart !== -1 && hourVal >= avoidStart && hourVal <= avoidEnd) {
                bar.classList.add('timeline__bar--avoid');
            } else {
                bar.classList.add('timeline__bar--neutral');
            }

            // Height scaling
            const heightPct = Math.max(rainVal, 10);
            bar.style.height = `${heightPct}%`;
            bar.style.transitionDelay = `${i * 35}ms`;

            // Sprout on first hour of best window
            if (hourVal === bestStart) {
                const sprout = document.createElement('div');
                sprout.className = 'bar-indicator sprout';
                sprout.textContent = '🌱';
                bar.appendChild(sprout);
            }

            // Dripping rain cloud on avoid window start
            if (hourVal === avoidStart) {
                const avoidCloud = document.createElement('div');
                avoidCloud.className = 'bar-indicator avoid-cloud';
                avoidCloud.innerHTML = `
                    <svg viewBox="0 0 24 20" width="20" height="18">
                        <path d="M5,12 A4,4 0 0,1 9,8 A5,5 0 0,1 18,9 A3,3 0 0,1 19,14 Z" fill="#94a3b8"/>
                        <line class="rain-drop drop-a" x1="7" y1="14" x2="6" y2="18" stroke="#38bdf8" stroke-width="1.5"/>
                        <line class="rain-drop drop-b" x1="12" y1="14" x2="11" y2="18" stroke="#38bdf8" stroke-width="1.5"/>
                        <line class="rain-drop drop-c" x1="17" y1="14" x2="16" y2="18" stroke="#38bdf8" stroke-width="1.5"/>
                    </svg>
                `;
                bar.appendChild(avoidCloud);
            }

            // Now marker
            if (hourVal === nowHour) {
                const nowMarker = document.createElement('div');
                nowMarker.className = 'now-marker';
                nowMarker.innerHTML = `<span class="now-badge">NOW</span><div class="now-line"></div>`;
                bar.appendChild(nowMarker);
            }

            // Hour label
            const label = document.createElement('span');
            label.className = 'timeline__label';
            const h12 = hourVal % 12 || 12;
            const ampm = hourVal < 12 ? 'am' : 'pm';
            label.textContent = `${h12}${ampm}`;
            bar.appendChild(label);

            // Tooltip events (hover & mobile tap)
            const tooltipText = `${h12} ${ampm} · 🌧 ${row.rain_prob} · 🌡 ${row.temp_pred}`;
            bar.addEventListener('pointerenter', (evt) => showTooltip(evt, tooltipText));
            bar.addEventListener('pointerleave', hideTooltip);
            bar.addEventListener('pointerdown', (evt) => {
                showTooltip(evt, tooltipText);
                evt.stopPropagation();
            });

            timeline.appendChild(bar);

            requestAnimationFrame(() => {
                bar.classList.add('loaded');
            });
        });
    }

    function showTooltip(evt, text) {
        const rect = evt.currentTarget.getBoundingClientRect();
        timelineTooltip.textContent = text;
        timelineTooltip.style.left = `${rect.left + rect.width / 2}px`;
        timelineTooltip.style.top = `${rect.top - 8}px`;
        timelineTooltip.classList.add('visible');
    }

    function hideTooltip() {
        timelineTooltip.classList.remove('visible');
    }

    document.addEventListener('pointerdown', hideTooltip);

    // -----------------------------------------------------------------------
    // Canvas Voice Waveform & Web Audio Engine (Part E)
    // -----------------------------------------------------------------------
    function initAudioContext() {
        if (!audioCtx) {
            audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        }
        if (audioCtx.state === 'suspended') {
            audioCtx.resume();
        }
    }

    function drawWaveform() {
        if (!currentAudio || currentAudio.paused || currentAudio.ended) {
            // Smoothly ease bars down
            pauseEaseProgress = Math.max(0, pauseEaseProgress - 0.1);
            renderCanvasFrame(new Uint8Array(256), pauseEaseProgress);
            if (pauseEaseProgress > 0) {
                waveformAnimId = requestAnimationFrame(drawWaveform);
            } else {
                cancelAnimationFrame(waveformAnimId);
                waveformAnimId = null;
            }
            return;
        }

        pauseEaseProgress = 1.0;
        waveformAnimId = requestAnimationFrame(drawWaveform);

        const bufferLength = analyser.frequencyBinCount;
        const dataArray = new Uint8Array(bufferLength);
        analyser.getByteFrequencyData(dataArray);

        renderCanvasFrame(dataArray, 1.0);
    }

    function renderCanvasFrame(dataArray, scaleFactor) {
        const ctx = waveformCanvas.getContext('2d');
        const width = waveformCanvas.width;
        const height = waveformCanvas.height;
        const centerX = width / 2;
        const centerY = height / 2;

        ctx.clearRect(0, 0, width, height);

        const isReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        const duration = currentAudio?.duration || 1;
        const currentTime = currentAudio?.currentTime || 0;
        const progress = Math.min(1, currentTime / duration);

        // 1. Progress Arc
        ctx.beginPath();
        ctx.arc(centerX, centerY, 44, -Math.PI / 2, -Math.PI / 2 + progress * 2 * Math.PI);
        ctx.strokeStyle = getComputedStyle(skyContainer).getPropertyValue('--waveform-bar').trim() || '#0284c7';
        ctx.lineWidth = 3;
        ctx.lineCap = 'round';
        ctx.stroke();

        if (isReducedMotion) {
            return;
        }

        // 2. Speech Frequency Range (80 Hz to ~4 kHz -> bins 0 to 22)
        const numBars = 56;
        const baseRadius = 45;
        let sumLoudness = 0;

        for (let i = 0; i < numBars; i++) {
            const angle = (i / numBars) * 2 * Math.PI - Math.PI / 2;
            const binIndex = Math.floor((i / numBars) * 22);
            const rawVal = dataArray[binIndex] || 0;
            sumLoudness += rawVal;

            const barLen = (rawVal / 255) * 22 * scaleFactor;

            const xStart = centerX + Math.cos(angle) * baseRadius;
            const yStart = centerY + Math.sin(angle) * baseRadius;
            const xEnd = centerX + Math.cos(angle) * (baseRadius + barLen);
            const yEnd = centerY + Math.sin(angle) * (baseRadius + barLen);

            ctx.beginPath();
            ctx.moveTo(xStart, yStart);
            ctx.lineTo(xEnd, yEnd);
            ctx.strokeStyle = ctx.strokeStyle;
            ctx.lineWidth = 2;
            ctx.lineCap = 'round';
            ctx.stroke();
        }

        // 3. Smoothed button pulse (1.00 to 1.05)
        const avgLoudness = sumLoudness / numBars;
        smoothedLoudness = smoothedLoudness * 0.8 + avgLoudness * 0.2;
        const btnScale = 1.0 + (smoothedLoudness / 255) * 0.05 * scaleFactor;
        playBtn.style.transform = `scale(${btnScale.toFixed(3)})`;
    }

    function stopAudio(unlock = true) {
        if (currentAbortController) {
            currentAbortController.abort();
            currentAbortController = null;
        }
        if (currentAudio) {
            currentAudio.pause();
            currentAudio.currentTime = 0;
            currentAudio = null;
        }
        if (waveformAnimId) {
            cancelAnimationFrame(waveformAnimId);
            waveformAnimId = null;
        }
        playIcon.textContent = '▶';
        playBtn.style.transform = 'scale(1)';
        const ctx = waveformCanvas.getContext('2d');
        ctx.clearRect(0, 0, waveformCanvas.width, waveformCanvas.height);
        if (unlock) {
            unlockChips();
        }
    }

    // -----------------------------------------------------------------------
    // Captions & Play Execution (Part E & Bug 2)
    // -----------------------------------------------------------------------
    function parseWordTimings(alignment) {
        if (!alignment || !alignment.characters) return null;
        const chars = alignment.characters;
        const starts = alignment.character_start_times_seconds;
        const ends = alignment.character_end_times_seconds;

        const words = [];
        let currWord = '';
        let startSec = null;
        let endSec = null;

        for (let i = 0; i < chars.length; i++) {
            const ch = chars[i];
            if (/\s/.test(ch)) {
                if (currWord.length > 0) {
                    words.push({ word: currWord, start: startSec, end: endSec });
                    currWord = '';
                    startSec = null;
                }
            } else {
                if (currWord.length === 0) startSec = starts[i];
                currWord += ch;
                endSec = ends[i];
            }
        }
        if (currWord.length > 0) {
            words.push({ word: currWord, start: startSec, end: endSec });
        }
        return words;
    }

    function buildCaptions(words, fullText) {
        captionsContainer.innerHTML = '';

        if (words && words.length > 0) {
            const spans = words.map(w => {
                const s = document.createElement('span');
                s.className = 'caption-word';
                s.textContent = w.word;
                captionsContainer.appendChild(s);
                // Explicit text node so spaces are never collapsed or lost
                captionsContainer.appendChild(document.createTextNode(' '));
                return { el: s, start: w.start, end: w.end };
            });

            return (currTime) => {
                spans.forEach(item => {
                    if (currTime >= item.start && currTime <= item.end) {
                        item.el.classList.add('word--active', 'word--spoken');
                    } else if (currTime > item.end) {
                        item.el.classList.remove('word--active');
                        item.el.classList.add('word--spoken');
                    } else {
                        item.el.classList.remove('word--active', 'word--spoken');
                    }
                });
            };
        }

        // Sentence fallback
        const sentences = fullText.match(/[^.!?]+[.!?]+(\s|$)/g) || [fullText];
        const sentSpans = sentences.map(st => {
            const s = document.createElement('span');
            s.className = 'caption-sentence';
            s.textContent = st;
            captionsContainer.appendChild(s);
            captionsContainer.appendChild(document.createTextNode(' '));
            return s;
        });

        return (currTime, duration) => {
            const fraction = currTime / (duration || 1);
            const activeIdx = Math.min(sentSpans.length - 1, Math.floor(fraction * sentSpans.length));
            sentSpans.forEach((el, idx) => {
                el.classList.toggle('active', idx === activeIdx);
            });
        };
    }

    function playBrief() {
        if (!briefData) {
            autoPlayPending = true;
            return;
        }

        brief.removeAttribute('hidden');
        if (briefData.fallback_note) {
            briefNote.textContent = briefData.fallback_note;
        }

        lockChips(currentActivity);

        // If audio file exists, play with Web Audio visualizer
        if (briefData.audio_file) {
            initAudioContext();

            if (currentAudio) {
                if (!currentAudio.paused) {
                    currentAudio.pause();
                    playIcon.textContent = '▶';
                    unlockChips();
                    return;
                } else {
                    currentAudio.play();
                    playIcon.textContent = '⏸';
                    lockChips(currentActivity);
                    waveformAnimId = requestAnimationFrame(drawWaveform);
                    return;
                }
            }

            const words = parseWordTimings(briefData.timings);
            captionController = buildCaptions(words, briefData.plan_text);

            currentAudio = new Audio(`/audio/${briefData.audio_file}`);

            if (!sourceNode) {
                analyser = audioCtx.createAnalyser();
                analyser.fftSize = 256;
                analyser.smoothingTimeConstant = 0.8;
                sourceNode = audioCtx.createMediaElementSource(currentAudio);
                sourceNode.connect(analyser);
                analyser.connect(audioCtx.destination);
            }

            currentAudio.addEventListener('timeupdate', () => {
                if (captionController) {
                    captionController(currentAudio.currentTime, currentAudio.duration);
                }
            });

            currentAudio.addEventListener('ended', () => {
                playIcon.textContent = '▶';
                stopAudio(true);

                // Audio ended celebration:
                grassGround.classList.add('grass--tall');
                const actor = document.getElementById('activeActor');
                if (actor) actor.classList.add('character--celebrating');

                outside.removeAttribute('hidden');
                outside.classList.add('outside--pop');
            });

            currentAudio.play().then(() => {
                playIcon.textContent = '⏸';
                waveformAnimId = requestAnimationFrame(drawWaveform);
            }).catch(err => {
                console.error(err);
                unlockChips();
            });

        } else {
            // Text-only mode: render text directly, reveal outside button
            captionsContainer.textContent = briefData.plan_text;
            outside.removeAttribute('hidden');
            outside.classList.add('outside--pop');
            unlockChips();
        }
    }


    playBtn.addEventListener('click', () => {
        playBrief();
    });

    // -----------------------------------------------------------------------
    // "I went outside" handler
    // -----------------------------------------------------------------------
    outsideBtn.addEventListener('click', () => {
        outsideBtn.setAttribute('hidden', '');
        outsideForm.removeAttribute('hidden');
    });

    outsideSubmit.addEventListener('click', () => {
        const note = outsideNote.value.trim();
        fetch('/went-outside', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ activity: currentActivity, note: note })
        }).then(res => res.json()).then(() => {
            outsideForm.setAttribute('hidden', '');
            outsideConfirm.removeAttribute('hidden');
        }).catch(console.error);
    });

    // -----------------------------------------------------------------------
    // Visibility & Lifecycle Handlers
    // -----------------------------------------------------------------------
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'hidden') {
            skyContainer.classList.add('anim-paused');
            if (waveformAnimId) {
                cancelAnimationFrame(waveformAnimId);
                waveformAnimId = null;
            }
        } else {
            skyContainer.classList.remove('anim-paused');
            if (currentAudio && !currentAudio.paused && !waveformAnimId) {
                waveformAnimId = requestAnimationFrame(drawWaveform);
            }
        }
    });

    window.addEventListener('beforeunload', () => {
        if (eventSource) eventSource.close();
        stopAudio();
    });
});
