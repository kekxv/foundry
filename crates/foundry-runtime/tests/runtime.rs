use foundry_runtime::*;
use serde_json::json;
use std::{collections::BTreeSet, time::Duration};
fn run(js: &str, ms: u64) -> anyhow::Result<serde_json::Value> {
    let d = tempfile::tempdir()?;
    std::fs::write(d.path().join("main.js"), js)?;
    let m = foundry_core::validate_manifest(&serde_json::to_vec(
        &json!({"schemaVersion":1,"id":"test","version":"1.0.0","description":"t","type":"javascript","entry":"main.js","platforms":["any"],"permissions":[],"capabilities":{"test":{"description":"t","export":"test","input":{},"output":{}}}}),
    )?)?;
    run_extension(
        d.path(),
        &m,
        "test",
        json!({}),
        RuntimeLimits {
            timeout: Duration::from_millis(ms),
            ..Default::default()
        },
        &BTreeSet::new(),
        None,
    )
}
#[test]
fn runs_exported_async_function() {
    assert_eq!(
        run(
            "export async function test(){return await Promise.resolve(42)}",
            1000
        )
        .unwrap(),
        json!(42)
    );
}
#[test]
fn interrupts_infinite_loop() {
    assert!(run("export function test(){while(true){}}", 50).is_err());
}
#[test]
fn times_out_pending_promise() {
    assert!(run("export function test(){return new Promise(()=>{})}", 50).is_err());
}
#[test]
fn rejects_non_json_result() {
    for value in [
        "undefined",
        "NaN",
        "Infinity",
        "1n",
        "(()=>{const a={};a.a=a;return a})()",
    ] {
        assert!(
            run(&format!("export function test(){{return {value}}}"), 1000).is_err(),
            "{value}"
        );
    }
}
#[test]
fn rejects_module_escape() {
    assert!(
        run(
            "import x from '../outside.js';export function test(){return x}",
            1000
        )
        .is_err()
    );
    assert!(
        run(
            "import * as os from 'std';export function test(){return os}",
            1000
        )
        .is_err()
    );
}
#[test]
fn supports_relative_modules() {
    let d = tempfile::tempdir().unwrap();
    std::fs::write(d.path().join("helper.js"), "export const value=7;").unwrap();
    std::fs::write(d.path().join("main.js"),"import {value} from './helper.js';export async function normalize(){return {text:String(value)}}").unwrap();
    let m = foundry_core::validate_manifest(include_bytes!(
        "../../../extensions/text-utils/0.1.0/manifest.json"
    ))
    .unwrap();
    assert_eq!(
        run_extension(
            d.path(),
            &m,
            "normalize",
            json!({"text":""}),
            Default::default(),
            &BTreeSet::new(),
            None
        )
        .unwrap(),
        json!({"text":"7"})
    );
}

#[test]
fn rejects_accessor_changing_value_during_serialization() {
    assert!(
        run(
            "export function test(){let n=0;return {get x(){return n++===0?1:NaN}}}",
            1000
        )
        .is_err()
    );
}
