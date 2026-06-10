alter table events drop constraint chk_events_item_types;

alter table events add constraint chk_events_item_types
  check (item_types <@ array['full_marathon', 'half_marathon', 'ten_kilometer']);
