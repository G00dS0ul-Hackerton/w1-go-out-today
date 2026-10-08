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

        // Evening banner
        if (hour >= 18 || hour < 5) {
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
    function renderCharacter(activity, rainProb) {
        characterStage.innerHTML = '';
        const actor = document.createElement('div');
        actor.className = 'activity-actor';
        actor.id = 'activeActor';

        const showUmbrella = rainProb >= 40;
        const umbrellaSVG = showUmbrella ? `
            <g class="umbrella-addon">
                <path d="M22,14 A14,14 0 0,1 48,14 Z" fill="#ef4444"/>
                <line x1="35" y1="14" x2="35" y2="34" stroke="#334155" stroke-width="2"/>
                <path d="M35,34 A3,3 0 0,1 30,34" fill="none" stroke="#334155" stroke-width="2"/>
            </g>
        ` : '';

        const act = activity.toLowerCase();
        if (act.includes('walk')) {
            actor.classList.add('actor-walk');
            actor.innerHTML = `
                <svg viewBox="0 0 70 80" width="70" height="80">
                    ${umbrellaSVG}
                    <circle cx="35" cy="18" r="8" fill="#1e293b"/>
                    <line x1="35" y1="26" x2="35" y2="52" stroke="#1e293b" stroke-width="6" stroke-linecap="round"/>
                    <line class="leg leg-left" x1="35" y1="52" x2="25" y2="76" stroke="#1e293b" stroke-width="4" stroke-linecap="round"/>
                    <line class="leg leg-right" x1="35" y1="52" x2="45" y2="76" stroke="#1e293b" stroke-width="4" stroke-linecap="round"/>
                </svg>
            `;
        } else if (act.includes('run')) {
            actor.classList.add('actor-run');
            actor.innerHTML = `
                <svg viewBox="0 0 70 80" width="70" height="80">
                    <circle cx="35" cy="18" r="8" fill="#1e293b"/>
                    <line x1="35" y1="26" x2="35" y2="52" stroke="#1e293b" stroke-width="6" stroke-linecap="round"/>
                    <line class="leg leg-left" x1="35" y1="52" x2="20" y2="76" stroke="#1e293b" stroke-width="4" stroke-linecap="round"/>
                    <line class="leg leg-right" x1="35" y1="52" x2="50" y2="76" stroke="#1e293b" stroke-width="4" stroke-linecap="round"/>
                </svg>
            `;
        } else if (act.includes('football')) {
            actor.classList.add('actor-football');
            actor.innerHTML = `
                <svg viewBox="0 0 100 80" width="100" height="80">
                    ${umbrellaSVG}
                    <circle cx="35" cy="20" r="7" fill="#1e293b"/>
                    <line x1="35" y1="27" x2="35" y2="52" stroke="#1e293b" stroke-width="5" stroke-linecap="round"/>
                    <line x1="35" y1="52" x2="25" y2="76" stroke="#1e293b" stroke-width="4" stroke-linecap="round"/>
                    <line class="kicking-leg" x1="35" y1="52" x2="48" y2="68" stroke="#1e293b" stroke-width="4" stroke-linecap="round"/>
                    <circle class="soccer-ball" cx="62" cy="72" r="6" fill="#f8fafc" stroke="#1e293b" stroke-width="2"/>
                </svg>
            `;
        } else if (act.includes('market')) {
            actor.classList.add('actor-market');
            actor.innerHTML = `
                <svg viewBox="0 0 70 80" width="70" height="80">
                    ${umbrellaSVG}
                    <circle cx="35" cy="18" r="8" fill="#1e293b"/>
                    <line x1="35" y1="26" x2="35" y2="52" stroke="#1e293b" stroke-width="6" stroke-linecap="round"/>
                    <line class="leg leg-left" x1="35" y1="52" x2="26" y2="76" stroke="#1e293b" stroke-width="4" stroke-linecap="round"/>
                    <line class="leg leg-right" x1="35" y1="52" x2="44" y2="76" stroke="#1e293b" stroke-width="4" stroke-linecap="round"/>
                    <g class="market-bag bag-left">
                        <rect x="14" y="44" width="12" height="16" rx="2" fill="#e11d48"/>
                    </g>
                    <g class="market-bag bag-right">
                        <rect x="44" y="44" width="12" height="16" rx="2" fill="#0284c7"/>
                    </g>
                </svg>
            `;
        } else if (act.includes('dry clothes')) {
            actor.classList.add('actor-clothes');
            actor.innerHTML = `
                <svg viewBox="0 0 160 90" width="160" height="90">
                    <line x1="10" y1="15" x2="10" y2="85" stroke="#78350f" stroke-width="4" stroke-linecap="round"/>
                    <line x1="150" y1="15" x2="150" y2="85" stroke="#78350f" stroke-width="4" stroke-linecap="round"/>
                    <path d="M10,25 Q80,36 150,25" fill="none" stroke="#94a3b8" stroke-width="2"/>
                    <g class="hanging-shirt shirt-1">
                        <path d="M30,30 L45,30 L48,38 L42,40 L40,55 L32,55 L30,40 L24,38 Z" fill="#3b82f6"/>
                    </g>
                    <g class="hanging-shirt shirt-2">
                        <path d="M75,32 L90,32 L93,40 L87,42 L85,57 L77,57 L75,42 L69,40 Z" fill="#ec4899"/>
                    </g>
                    <g class="hanging-shirt shirt-3">
                        <path d="M115,31 L132,31 L134,60 L126,60 L123.5,45 L121,60 L113,60 Z" fill="#64748b"/>
                    </g>
                </svg>
            `;
        } else if (act.includes('commute')) {
            actor.classList.add('actor-danfo');
            actor.innerHTML = `
                <svg viewBox="0 0 120 70" width="120" height="70">
                    <rect x="10" y="20" width="95" height="34" rx="5" fill="#facc15"/>
                    <rect x="10" y="36" width="95" height="4" fill="#0f172a"/>
                    <rect x="10" y="44" width="95" height="4" fill="#0f172a"/>
                    <rect x="18" y="24" width="18" height="10" rx="2" fill="#38bdf8"/>
                    <rect x="42" y="24" width="22" height="10" rx="2" fill="#38bdf8"/>
                    <rect x="70" y="24" width="28" height="10" rx="2" fill="#38bdf8"/>
                    <circle class="danfo-wheel" cx="32" cy="54" r="8" fill="#1e293b"/>
                    <circle cx="32" cy="54" r="3" fill="#94a3b8"/>
                    <circle class="danfo-wheel" cx="85" cy="54" r="8" fill="#1e293b"/>
                    <circle cx="85" cy="54" r="3" fill="#94a3b8"/>
                </svg>
            `;
        } else if (act.includes('picnic')) {
            actor.classList.add('actor-picnic');
            actor.innerHTML = `
                <svg viewBox="0 0 120 70" width="120" height="70">
                    ${umbrellaSVG}
                    <polygon points="10,65 110,65 95,50 25,50" fill="#f43f5e"/>
                    <rect x="35" y="45" width="20" height="14" rx="2" fill="#b45309"/>
                    <circle cx="75" cy="32" r="7" fill="#1e293b"/>
                    <path d="M75,39 L75,54 L62,56" fill="none" stroke="#1e293b" stroke-width="5" stroke-linecap="round"/>
                </svg>
            `;
        } else if (act.includes('hangout')) {
            actor.classList.add('actor-hangout');
            actor.innerHTML = `
                <svg viewBox="0 0 130 80" width="130" height="80">
                    ${umbrellaSVG}
                    <circle cx="45" cy="28" r="7" fill="#1e293b"/>
                    <line x1="45" y1="35" x2="45" y2="65" stroke="#1e293b" stroke-width="5" stroke-linecap="round"/>
                    <circle cx="70" cy="30" r="7" fill="#1e293b"/>
                    <line x1="70" y1="37" x2="70" y2="65" stroke="#1e293b" stroke-width="5" stroke-linecap="round"/>
                    <g class="balloon-group">
                        <path d="M85,15 A8,10 0 1,1 84.9,15 Z" fill="#8b5cf6"/>
                        <path d="M85,25 Q82,38 78,48" fill="none" stroke="#cbd5e1" stroke-width="1.5"/>
                        <path d="M96,18 A7,9 0 1,1 95.9,18 Z" fill="#f43f5e"/>
                    </g>
                    <text class="music-note" x="52" y="18" font-size="14" fill="#f59e0b">♪</text>
                </svg>
            `;
        }
        characterStage.appendChild(actor);
    }

    renderCharacter(currentActivity, currentRainProb);

    // -----------------------------------------------------------------------
    // Chips & Activity Management
    // -----------------------------------------------------------------------
    function updateChips(activeActivity) {
        chips.forEach(chip => {
            if (chip.dataset.activity === activeActivity) {
                chip.classList.add('chip--active');
            } else {
                chip.classList.remove('chip--active');
            }
        });
    }

    updateChips(currentActivity);

    chips.forEach(chip => {
        chip.addEventListener('click', (e) => {
            const newAct = e.target.dataset.activity;
            if (newAct === currentActivity) return;

            // Stop any playing audio cleanly to prevent double audio
            stopAudio();

            currentActivity = newAct;
            localStorage.setItem('activity', currentActivity);
            updateChips(currentActivity);
            renderCharacter(currentActivity, currentRainProb);
            startBrief(currentActivity);
        });
    });

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
    // Pipeline & SSE Management
    // -----------------------------------------------------------------------
    function startBrief(activity) {
        if (eventSource) {
            eventSource.close();
        }

        briefData = null;
        autoPlayPending = false;
        statusDot.className = 'play-btn__dot dot--building';
        playIcon.textContent = '▶';

        resetStepsUI();
        timeline.setAttribute('hidden', '');
        brief.setAttribute('hidden', '');
        outside.setAttribute('hidden', '');
        outsideBtn.removeAttribute('hidden');
        outsideForm.setAttribute('hidden', '');
        if (outsideConfirm) outsideConfirm.setAttribute('hidden', '');
        grassGround.classList.remove('grass--tall');

        fetch('/brief', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ activity: activity })
        }).catch(console.error);

        eventSource = new EventSource('/events');

        eventSource.addEventListener('progress', (e) => {
            const data = JSON.parse(e.data);
            if (data.status === 'running') {
                showActiveStep(data.step);
            } else if (data.status === 'done') {
                markStepDone(data.step);
            }
        });

        eventSource.addEventListener('forecast_ready', (e) => {
            const data = JSON.parse(e.data);
            cachedForecast = data.forecast;
            renderTimeline(data.forecast, data.facts);

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
            briefData = JSON.parse(e.data);
            activeStepContainer.setAttribute('hidden', '');
            statusDot.className = 'play-btn__dot dot--ready';

            if (autoPlayPending) {
                playBrief();
            }
            if (eventSource) eventSource.close();
        });

        eventSource.addEventListener('error', (e) => {
            console.warn('SSE event error:', e);
        });
    }

    startBrief(currentActivity);

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

    function stopAudio() {
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
    }

    // -----------------------------------------------------------------------
    // Captions & Play Execution (Part E)
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
                s.textContent = w.word + ' ';
                captionsContainer.appendChild(s);
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

        // If audio file exists, play with Web Audio visualizer
        if (briefData.audio_file) {
            initAudioContext();

            if (currentAudio) {
                if (!currentAudio.paused) {
                    currentAudio.pause();
                    playIcon.textContent = '▶';
                    return;
                } else {
                    currentAudio.play();
                    playIcon.textContent = '⏸';
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
                stopAudio();

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
            }).catch(console.error);

        } else {
            // Text-only mode: render text directly, reveal outside button
            captionsContainer.textContent = briefData.plan_text;
            outside.removeAttribute('hidden');
            outside.classList.add('outside--pop');
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
