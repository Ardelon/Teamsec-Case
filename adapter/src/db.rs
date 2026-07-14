use crate::types::{ParsedCredit, ParsedPayment, PipelineError};
use chrono::{DateTime, NaiveDate, Utc};
use postgres_types::ToSql;
use serde_json::Value;
use std::collections::HashMap;
use tokio_postgres::Client;

const CREDIT_BATCH_SIZE: usize = 2_000;
const PAYMENT_BATCH_SIZE: usize = 2_000;
const CREDIT_INSERT_CHUNK: usize = 100;
const PAYMENT_INSERT_CHUNK: usize = 200;
const CREDIT_COLS: usize = 29;
const PAYMENT_COLS: usize = 14;

fn date_param(value: &Option<String>) -> Option<NaiveDate> {
    value
        .as_ref()
        .and_then(|v| NaiveDate::parse_from_str(v, "%Y-%m-%d").ok())
}

fn format_db_error(err: &tokio_postgres::Error) -> String {
    err.as_db_error()
        .map(|db| format!("{} ({})", db.message(), db.code().code()))
        .unwrap_or_else(|| err.to_string())
}

struct CreditRowBind {
    loan_account_number: String,
    customer_id: String,
    customer_type: String,
    loan_status_code: String,
    days_past_due: Option<i32>,
    final_maturity_date: Option<NaiveDate>,
    total_installment_count: Option<i32>,
    outstanding_installment_count: Option<i32>,
    paid_installment_count: Option<i32>,
    first_payment_date: Option<NaiveDate>,
    original_loan_amount: Option<String>,
    outstanding_principal_balance: Option<String>,
    nominal_interest_rate: Option<String>,
    total_interest_amount: Option<String>,
    kkdf_rate: Option<String>,
    kkdf_amount: Option<String>,
    bsmv_rate: Option<String>,
    bsmv_amount: Option<String>,
    grace_period_months: Option<i32>,
    installment_frequency: Option<i32>,
    loan_start_date: Option<NaiveDate>,
    loan_closing_date: Option<NaiveDate>,
    internal_rating: Option<i32>,
    external_rating: Option<i32>,
    retail_specific_attributes: Value,
    commercial_specific_attributes: Value,
}

impl CreditRowBind {
    fn from_credit(credit: ParsedCredit) -> Self {
        Self {
            loan_account_number: credit.loan_account_number,
            customer_id: credit.customer_id,
            customer_type: credit.customer_type,
            loan_status_code: credit.loan_status_code,
            days_past_due: credit.days_past_due,
            final_maturity_date: date_param(&credit.final_maturity_date),
            total_installment_count: credit.total_installment_count,
            outstanding_installment_count: credit.outstanding_installment_count,
            paid_installment_count: credit.paid_installment_count,
            first_payment_date: date_param(&credit.first_payment_date),
            original_loan_amount: credit.original_loan_amount,
            outstanding_principal_balance: credit.outstanding_principal_balance,
            nominal_interest_rate: credit.nominal_interest_rate,
            total_interest_amount: credit.total_interest_amount,
            kkdf_rate: credit.kkdf_rate,
            kkdf_amount: credit.kkdf_amount,
            bsmv_rate: credit.bsmv_rate,
            bsmv_amount: credit.bsmv_amount,
            grace_period_months: credit.grace_period_months,
            installment_frequency: credit.installment_frequency,
            loan_start_date: date_param(&credit.loan_start_date),
            loan_closing_date: date_param(&credit.loan_closing_date),
            internal_rating: credit.internal_rating,
            external_rating: credit.external_rating,
            retail_specific_attributes: credit.retail_specific_attributes,
            commercial_specific_attributes: credit.commercial_specific_attributes,
        }
    }
}

struct PaymentRowBind {
    credit_id: i64,
    installment_number: i32,
    actual_payment_date: Option<NaiveDate>,
    scheduled_payment_date: Option<NaiveDate>,
    installment_amount: Option<String>,
    principal_component: Option<String>,
    interest_component: Option<String>,
    kkdf_component: Option<String>,
    bsmv_component: Option<String>,
    installment_status: String,
    remaining_principal: Option<String>,
    remaining_interest: Option<String>,
    remaining_kkdf: Option<String>,
    remaining_bsmv: Option<String>,
}

pub struct SnapshotWriter<'a> {
    transaction: tokio_postgres::Transaction<'a>,
    tenant_id: String,
    loan_type: String,
    credit_id_map: HashMap<String, i64>,
    credit_batch: Vec<ParsedCredit>,
    payment_batch: Vec<ParsedPayment>,
    payments_ingested: u64,
}

impl<'a> SnapshotWriter<'a> {
    pub async fn begin(
        client: &'a mut Client,
        tenant_id: &str,
        loan_type: &str,
    ) -> Result<Self, PipelineError> {
        let tenant_id = tenant_id.to_string();
        let loan_type = loan_type.to_string();

        let transaction = client
            .transaction()
            .await
            .map_err(|e| PipelineError::Database(e.to_string()))?;

        transaction
            .execute(
                "DELETE FROM etl_paymentinstallment WHERE credit_id IN (
                    SELECT id FROM etl_creditrecord WHERE tenant_id = $1 AND loan_type = $2
                )",
                &[&tenant_id, &loan_type],
            )
            .await
            .map_err(|e| PipelineError::Database(e.to_string()))?;

        transaction
            .execute(
                "DELETE FROM etl_creditrecord WHERE tenant_id = $1 AND loan_type = $2",
                &[&tenant_id, &loan_type],
            )
            .await
            .map_err(|e| PipelineError::Database(e.to_string()))?;

        Ok(Self {
            transaction,
            tenant_id,
            loan_type,
            credit_id_map: HashMap::new(),
            credit_batch: Vec::with_capacity(CREDIT_BATCH_SIZE),
            payment_batch: Vec::with_capacity(PAYMENT_BATCH_SIZE),
            payments_ingested: 0,
        })
    }

    pub fn credits_ingested(&self) -> u64 {
        self.credit_id_map.len() as u64
    }

    pub async fn push_credit(&mut self, credit: ParsedCredit) -> Result<(), PipelineError> {
        self.credit_batch.push(credit);
        if self.credit_batch.len() >= CREDIT_BATCH_SIZE {
            self.flush_credits().await?;
        }
        Ok(())
    }

    pub async fn flush_credits(&mut self) -> Result<(), PipelineError> {
        if self.credit_batch.is_empty() {
            return Ok(());
        }

        let credits =
            std::mem::replace(&mut self.credit_batch, Vec::with_capacity(CREDIT_BATCH_SIZE));

        let mut deduped: Vec<ParsedCredit> = Vec::with_capacity(credits.len());
        let mut index: HashMap<String, usize> = HashMap::with_capacity(credits.len());
        for credit in credits {
            if let Some(&pos) = index.get(&credit.loan_account_number) {
                deduped[pos] = credit;
            } else {
                index.insert(credit.loan_account_number.clone(), deduped.len());
                deduped.push(credit);
            }
        }

        for chunk in deduped.chunks(CREDIT_INSERT_CHUNK) {
            self.insert_credits_multi(chunk).await?;
        }
        Ok(())
    }

    async fn insert_credits_multi(&mut self, credits: &[ParsedCredit]) -> Result<(), PipelineError> {
        if credits.is_empty() {
            return Ok(());
        }

        let snapshot_at: DateTime<Utc> = Utc::now();
        let binds: Vec<CreditRowBind> = credits
            .iter()
            .cloned()
            .map(CreditRowBind::from_credit)
            .collect();

        let mut sql = String::from(
            "INSERT INTO etl_creditrecord (
                tenant_id, loan_type, loan_account_number, customer_id, customer_type,
                loan_status_code, days_past_due, final_maturity_date, total_installment_count,
                outstanding_installment_count, paid_installment_count, first_payment_date,
                original_loan_amount, outstanding_principal_balance, nominal_interest_rate,
                total_interest_amount, kkdf_rate, kkdf_amount, bsmv_rate, bsmv_amount,
                grace_period_months, installment_frequency, loan_start_date, loan_closing_date,
                internal_rating, external_rating, retail_specific_attributes,
                commercial_specific_attributes, snapshot_at
            ) VALUES ",
        );

        let mut params: Vec<&(dyn ToSql + Sync)> = Vec::with_capacity(binds.len() * CREDIT_COLS);
        for (i, row) in binds.iter().enumerate() {
            if i > 0 {
                sql.push(',');
            }
            let base = i * CREDIT_COLS;
            sql.push('(');
            for c in 0..CREDIT_COLS {
                if c > 0 {
                    sql.push(',');
                }
                let idx = base + c + 1;
                match c {
                    12 | 13 | 14 | 15 | 16 | 17 | 18 | 19 => {
                        sql.push_str(&format!("${idx}::text::numeric"));
                    }
                    _ => sql.push_str(&format!("${idx}")),
                }
            }
            sql.push(')');

            params.extend_from_slice(&[
                &self.tenant_id,
                &self.loan_type,
                &row.loan_account_number,
                &row.customer_id,
                &row.customer_type,
                &row.loan_status_code,
                &row.days_past_due,
                &row.final_maturity_date,
                &row.total_installment_count,
                &row.outstanding_installment_count,
                &row.paid_installment_count,
                &row.first_payment_date,
                &row.original_loan_amount,
                &row.outstanding_principal_balance,
                &row.nominal_interest_rate,
                &row.total_interest_amount,
                &row.kkdf_rate,
                &row.kkdf_amount,
                &row.bsmv_rate,
                &row.bsmv_amount,
                &row.grace_period_months,
                &row.installment_frequency,
                &row.loan_start_date,
                &row.loan_closing_date,
                &row.internal_rating,
                &row.external_rating,
                &row.retail_specific_attributes,
                &row.commercial_specific_attributes,
                &snapshot_at,
            ]);
        }

        sql.push_str(
            " ON CONFLICT (tenant_id, loan_type, loan_account_number) DO UPDATE SET
                customer_id = EXCLUDED.customer_id,
                customer_type = EXCLUDED.customer_type,
                loan_status_code = EXCLUDED.loan_status_code,
                days_past_due = EXCLUDED.days_past_due,
                final_maturity_date = EXCLUDED.final_maturity_date,
                total_installment_count = EXCLUDED.total_installment_count,
                outstanding_installment_count = EXCLUDED.outstanding_installment_count,
                paid_installment_count = EXCLUDED.paid_installment_count,
                first_payment_date = EXCLUDED.first_payment_date,
                original_loan_amount = EXCLUDED.original_loan_amount,
                outstanding_principal_balance = EXCLUDED.outstanding_principal_balance,
                nominal_interest_rate = EXCLUDED.nominal_interest_rate,
                total_interest_amount = EXCLUDED.total_interest_amount,
                kkdf_rate = EXCLUDED.kkdf_rate,
                kkdf_amount = EXCLUDED.kkdf_amount,
                bsmv_rate = EXCLUDED.bsmv_rate,
                bsmv_amount = EXCLUDED.bsmv_amount,
                grace_period_months = EXCLUDED.grace_period_months,
                installment_frequency = EXCLUDED.installment_frequency,
                loan_start_date = EXCLUDED.loan_start_date,
                loan_closing_date = EXCLUDED.loan_closing_date,
                internal_rating = EXCLUDED.internal_rating,
                external_rating = EXCLUDED.external_rating,
                retail_specific_attributes = EXCLUDED.retail_specific_attributes,
                commercial_specific_attributes = EXCLUDED.commercial_specific_attributes,
                snapshot_at = EXCLUDED.snapshot_at
            RETURNING loan_account_number, id",
        );

        let rows = self
            .transaction
            .query(&sql, &params[..])
            .await
            .map_err(|e| PipelineError::Database(format!("credit batch: {}", format_db_error(&e))))?;

        for row in rows {
            let account: String = row.get(0);
            let id: i64 = row.get(1);
            self.credit_id_map.insert(account, id);
        }

        Ok(())
    }

    pub async fn push_payment(&mut self, payment: ParsedPayment) -> Result<(), PipelineError> {
        self.payment_batch.push(payment);
        if self.payment_batch.len() >= PAYMENT_BATCH_SIZE {
            self.flush_payments().await?;
        }
        Ok(())
    }

    pub async fn flush_payments(&mut self) -> Result<(), PipelineError> {
        if self.payment_batch.is_empty() {
            return Ok(());
        }

        let payments =
            std::mem::replace(&mut self.payment_batch, Vec::with_capacity(PAYMENT_BATCH_SIZE));

        let mut binds: Vec<PaymentRowBind> = Vec::with_capacity(payments.len());
        for payment in payments {
            let credit_id = *self.credit_id_map.get(&payment.loan_account_number).ok_or_else(|| {
                PipelineError::Database(format!(
                    "missing credit id for {}",
                    payment.loan_account_number
                ))
            })?;

            binds.push(PaymentRowBind {
                credit_id,
                installment_number: payment.installment_number,
                actual_payment_date: date_param(&payment.actual_payment_date),
                scheduled_payment_date: date_param(&payment.scheduled_payment_date),
                installment_amount: payment.installment_amount,
                principal_component: payment.principal_component,
                interest_component: payment.interest_component,
                kkdf_component: payment.kkdf_component,
                bsmv_component: payment.bsmv_component,
                installment_status: payment.installment_status,
                remaining_principal: payment.remaining_principal,
                remaining_interest: payment.remaining_interest,
                remaining_kkdf: payment.remaining_kkdf,
                remaining_bsmv: payment.remaining_bsmv,
            });
        }

        for chunk in binds.chunks(PAYMENT_INSERT_CHUNK) {
            self.insert_payments_multi(chunk).await?;
        }
        Ok(())
    }

    async fn insert_payments_multi(&mut self, payments: &[PaymentRowBind]) -> Result<(), PipelineError> {
        if payments.is_empty() {
            return Ok(());
        }

        let mut sql = String::from(
            "INSERT INTO etl_paymentinstallment (
                credit_id, installment_number, actual_payment_date, scheduled_payment_date,
                installment_amount, principal_component, interest_component, kkdf_component,
                bsmv_component, installment_status, remaining_principal, remaining_interest,
                remaining_kkdf, remaining_bsmv
            ) VALUES ",
        );

        let mut params: Vec<&(dyn ToSql + Sync)> = Vec::with_capacity(payments.len() * PAYMENT_COLS);
        for (i, row) in payments.iter().enumerate() {
            if i > 0 {
                sql.push(',');
            }
            let base = i * PAYMENT_COLS;
            sql.push('(');
            for c in 0..PAYMENT_COLS {
                if c > 0 {
                    sql.push(',');
                }
                let idx = base + c + 1;
                match c {
                    4 | 5 | 6 | 7 | 8 | 10 | 11 | 12 | 13 => {
                        sql.push_str(&format!("${idx}::text::numeric"));
                    }
                    _ => sql.push_str(&format!("${idx}")),
                }
            }
            sql.push(')');

            params.extend_from_slice(&[
                &row.credit_id,
                &row.installment_number,
                &row.actual_payment_date,
                &row.scheduled_payment_date,
                &row.installment_amount,
                &row.principal_component,
                &row.interest_component,
                &row.kkdf_component,
                &row.bsmv_component,
                &row.installment_status,
                &row.remaining_principal,
                &row.remaining_interest,
                &row.remaining_kkdf,
                &row.remaining_bsmv,
            ]);
        }

        self.transaction
            .execute(&sql, &params[..])
            .await
            .map_err(|e| {
                PipelineError::Database(format!("payment batch: {}", format_db_error(&e)))
            })?;

        self.payments_ingested += payments.len() as u64;
        Ok(())
    }

    pub async fn commit(mut self) -> Result<u64, PipelineError> {
        self.flush_credits().await?;
        self.flush_payments().await?;
        self.transaction
            .commit()
            .await
            .map_err(|e| PipelineError::Database(e.to_string()))?;
        Ok(self.payments_ingested)
    }
}

pub async fn open_database_client(
    database_url: &str,
) -> Result<(Client, tokio::task::JoinHandle<()>), PipelineError> {
    let (client, connection) = tokio_postgres::connect(database_url, tokio_postgres::NoTls)
        .await
        .map_err(|e| PipelineError::Database(e.to_string()))?;

    let connection_task = tokio::spawn(async move {
        if let Err(e) = connection.await {
            eprintln!("postgres connection error: {e}");
        }
    });

    Ok((client, connection_task))
}
