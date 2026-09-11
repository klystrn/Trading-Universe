"""System and data health (spec sections 32, 42)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from trading_universe.api.deps import platform_dep
from trading_universe.services.platform import Platform

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/health")
def health(platform: Platform = Depends(platform_dep)) -> dict:
    return platform.health.snapshot().model_dump(mode="json")


@router.get("/freshness")
def freshness(platform: Platform = Depends(platform_dep)) -> dict:
    states = platform.freshness.all_states()
    return {
        "overall": platform.freshness.overall_status().value,
        "sources": [s.model_dump(mode="json") for s in states],
        "strategy_gates": platform.health.strategy_gates(),
    }


@router.get("/status")
def status(platform: Platform = Depends(platform_dep)) -> dict:
    """The compact System tab panel."""
    snapshot = platform.health.snapshot()
    last_scan = platform.scanner.last_result
    return {
        "moomoo": "CONNECTED" if platform.market_data.connected else "DISCONNECTED",
        "provider": getattr(platform.provider, "name", "unknown"),
        "quotes": snapshot.overall.value,
        "database": "HEALTHY" if snapshot.database_healthy else "ERROR",
        "scanner": "RUNNING" if snapshot.scanner_running else "STOPPED",
        "execution": platform.execution.operating_mode.value,
        "auto_trade": "ARMED" if snapshot.auto_trade_enabled else "DISABLED",
        "kill_switch": snapshot.kill_switch_engaged,
        "trading_env": snapshot.trading_env,
        "allow_real_orders": snapshot.allow_real_orders,
        "read_only": snapshot.read_only,
        "session": snapshot.session,
        "open_orders": snapshot.open_orders,
        "rejected_orders_today": snapshot.rejected_orders_today,
        "last_scan_at": last_scan.finished_at.isoformat() if last_scan else None,
        "last_scan_duration_s": last_scan.duration_seconds if last_scan else None,
        "last_sync_at": snapshot.last_sync_at.isoformat() if snapshot.last_sync_at else None,
        "market_data": platform.market_data.stats(),
    }


@router.post("/kill-switch")
def kill_switch(engage: bool = True, platform: Platform = Depends(platform_dep)) -> dict:
    """STOP ALL TRADING (spec section 42)."""
    if engage:
        platform.execution.engage_kill_switch()
    else:
        platform.execution.release_kill_switch()
    return {"kill_switch_engaged": engage}


@router.post("/mode")
def set_mode(mode: str, platform: Platform = Depends(platform_dep)) -> dict:
    """Change operating mode. LIVE_AUTO additionally requires the environment
    interlocks and explicit arming - setting the mode alone changes nothing."""
    from trading_universe.domain.enums import OperatingMode

    try:
        parsed = OperatingMode(mode.upper())
    except ValueError as exc:
        raise HTTPException(400, f"unknown mode: {mode}") from exc

    platform.execution.set_operating_mode(parsed)
    response: dict = {"operating_mode": parsed.value, "auto_trade_armed": False}
    if parsed is OperatingMode.LIVE_AUTO:
        from trading_universe.execution.live import check_live_gates

        gate = check_live_gates(parsed, platform.execution.auto_trade_armed)
        response["live_gates"] = {"permitted": gate.permitted, "blocking": gate.failures}
    return response


@router.post("/arm")
def arm_auto_trade(armed: bool, platform: Platform = Depends(platform_dep)) -> dict:
    """Arm or disarm automatic execution. This is the UI half of the live
    interlock; the environment half cannot be set from here by design."""
    platform.execution.arm_auto_trade(armed)
    return {"auto_trade_armed": platform.execution.auto_trade_armed}


@router.post("/scan")
def trigger_scan(execute: bool = False, platform: Platform = Depends(platform_dep)) -> dict:
    result = platform.refresh(execute=execute)
    return {
        "tickers_scanned": result.tickers_scanned,
        "signals": len(result.signals),
        "executable": len(result.executable),
        "orders_placed": result.orders_placed,
        "duration_seconds": result.duration_seconds,
        "regime": result.regime.regime.value if result.regime else None,
        "error": result.error,
    }
