# Databricks notebook source

print("Hello from Databricks Asset Bundle")

dbutils.widgets.text("environment", "unknown")
environment = dbutils.widgets.get("environment")

print(f"Running in environment: {environment}")