use crate::types::{ParsedCredit, ParsedPayment, PipelineError};
use chrono::{DateTime, NaiveDate, Utc};
use postgres_types::Json;
use std::collections::HashMap;
use tokio_postgres::Client;

const CREDIT_BATCH_SIZE: usize = 500;
const PAYMENT_BATCH_SIZE: usize = 1000;

fn date_param(value: &Option<String>) -> Option<NaiveDate> {
    value
        .as_ref()
        .and_then(|v| NaiveDate::parse_from_str(v, "%Y-%m-%d").ok())
}

fn text_param(value: &Option<String>) -> Option<&str> {
    value.as_deref()
}

pub struct SnapshotWriter<'a> {
    transaction: tokio_postgres::Transaction<'a>,
    tenant_id: String,
    loan_type: String,
    credit_id_map: HashMap<String, i64>,
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
            payment_batch: Vec::with_capacity(PAYMENT_BATCH_SIZE),
            payments_ingested: 0,
        })
    }

    pub async fn insert_credits(&mut self, credits: &[ParsedCredit]) -> Result<(), PipelineError> {
        for chunk in credits.chunks(CREDIT_BATCH_SIZE) {
            for credit in chunk {
                let final_maturity_date = date_param(&credit.final_maturity_date);
                let first_payment_date = date_param(&credit.first_payment_date);
                let loan_start_date = date_param(&credit.loan_start_date);
                let loan_closing_date = date_param(&credit.loan_closing_date);
                let original_loan_amount = text_param(&credit.original_loan_amount);
                let outstanding_principal_balance = text_param(&credit.outstanding_principal_balance);
                let nominal_interest_rate = text_param(&credit.nominal_interest_rate);
                let total_interest_amount = text_param(&credit.total_interest_amount);
                let kkdf_rate = text_param(&credit.kkdf_rate);
                let kkdf_amount = text_param(&credit.kkdf_amount);
                let bsmv_rate = text_param(&credit.bsmv_rate);
                let bsmv_amount = text_param(&credit.bsmv_amount);
                let retail_attrs = Json(&credit.retail_specific_attributes);
                let commercial_attrs = Json(&credit.commercial_specific_attributes);
                let snapshot_at: DateTime<Utc> = Utc::now();

                let row = self
                    .transaction
                    .query_one(
                        "INSERT INTO etl_creditrecord (
                            tenant_id, loan_type, loan_account_number, customer_id, customer_type,
                            loan_status_code, days_past_due, final_maturity_date, total_installment_count,
                            outstanding_installment_count, paid_installment_count, first_payment_date,
                            original_loan_amount, outstanding_principal_balance, nominal_interest_rate,
                            total_interest_amount, kkdf_rate, kkdf_amount, bsmv_rate, bsmv_amount,
                            grace_period_months, installment_frequency, loan_start_date, loan_closing_date,
                            internal_rating, external_rating, retail_specific_attributes,
                            commercial_specific_attributes, snapshot_at
                        ) VALUES (
                            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12,
                            $13::text::numeric, $14::text::numeric, $15::text::numeric, $16::text::numeric,
                            $17::text::numeric, $18::text::numeric, $19::text::numeric, $20::text::numeric,
                            $21, $22, $23, $24, $25, $26, $27, $28, $29
                        ) RETURNING id",
                        &[
                            &self.tenant_id,
                            &self.loan_type,
                            &credit.loan_account_number,
                            &credit.customer_id,
                            &credit.customer_type,
                            &credit.loan_status_code,
                            &credit.days_past_due,
                            &final_maturity_date,
                            &credit.total_installment_count,
                            &credit.outstanding_installment_count,
                            &credit.paid_installment_count,
                            &first_payment_date,
                            &original_loan_amount,
                            &outstanding_principal_balance,
                            &nominal_interest_rate,
                            &total_interest_amount,
                            &kkdf_rate,
                            &kkdf_amount,
                            &bsmv_rate,
                            &bsmv_amount,
                            &credit.grace_period_months,
                            &credit.installment_frequency,
                            &loan_start_date,
                            &loan_closing_date,
                            &credit.internal_rating,
                            &credit.external_rating,
                            &retail_attrs,
                            &commercial_attrs,
                            &snapshot_at,
                        ],
                    )
                    .await
                    .map_err(|e| {
                        PipelineError::Database(format!(
                            "credit {}: {}",
                            credit.loan_account_number, e
                        ))
                    })?;

                let id: i64 = row.get(0);
                self.credit_id_map
                    .insert(credit.loan_account_number.clone(), id);
            }
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

        for payment in self.payment_batch.drain(..) {
            let credit_id = *self.credit_id_map.get(&payment.loan_account_number).ok_or_else(|| {
                PipelineError::Database(format!(
                    "missing credit id for {}",
                    payment.loan_account_number
                ))
            })?;

            let actual_payment_date = date_param(&payment.actual_payment_date);
            let scheduled_payment_date = date_param(&payment.scheduled_payment_date);
            let installment_amount = text_param(&payment.installment_amount);
            let principal_component = text_param(&payment.principal_component);
            let interest_component = text_param(&payment.interest_component);
            let kkdf_component = text_param(&payment.kkdf_component);
            let bsmv_component = text_param(&payment.bsmv_component);
            let remaining_principal = text_param(&payment.remaining_principal);
            let remaining_interest = text_param(&payment.remaining_interest);
            let remaining_kkdf = text_param(&payment.remaining_kkdf);
            let remaining_bsmv = text_param(&payment.remaining_bsmv);

            self.transaction
                .execute(
                    "INSERT INTO etl_paymentinstallment (
                        credit_id, installment_number, actual_payment_date, scheduled_payment_date,
                        installment_amount, principal_component, interest_component, kkdf_component,
                        bsmv_component, installment_status, remaining_principal, remaining_interest,
                        remaining_kkdf, remaining_bsmv
                    ) VALUES (
                        $1, $2, $3, $4,
                        $5::text::numeric, $6::text::numeric, $7::text::numeric, $8::text::numeric, $9::text::numeric,
                        $10, $11::text::numeric, $12::text::numeric, $13::text::numeric, $14::text::numeric
                    )",
                    &[
                        &credit_id,
                        &payment.installment_number,
                        &actual_payment_date,
                        &scheduled_payment_date,
                        &installment_amount,
                        &principal_component,
                        &interest_component,
                        &kkdf_component,
                        &bsmv_component,
                        &payment.installment_status,
                        &remaining_principal,
                        &remaining_interest,
                        &remaining_kkdf,
                        &remaining_bsmv,
                    ],
                )
                .await
                .map_err(|e| {
                    PipelineError::Database(format!(
                        "payment {}#{}: {}",
                        payment.loan_account_number, payment.installment_number, e
                    ))
                })?;

            self.payments_ingested += 1;
        }

        Ok(())
    }

    pub async fn commit(mut self) -> Result<u64, PipelineError> {
        self.flush_payments().await?;
        self.transaction
            .commit()
            .await
            .map_err(|e| PipelineError::Database(e.to_string()))?;
        Ok(self.payments_ingested)
    }
}

pub async fn open_database_client(database_url: &str) -> Result<(Client, tokio::task::JoinHandle<()>), PipelineError> {
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
